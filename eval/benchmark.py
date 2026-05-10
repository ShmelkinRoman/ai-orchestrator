"""
Benchmark: Qwen-32B vs Sonnet-4.6 as code executors.

Usage:
    python3 eval/benchmark.py                  # all tasks
    python3 eval/benchmark.py format_cost      # single task
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Bootstrap path so we can import project config
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import GITHUB_TOKEN, GITHUB_REPO, OPENROUTER_API_KEY, QWEN_API_BASE  # noqa: E402
from eval.tasks import TASKS  # noqa: E402

AIDER_CMD = shutil.which("aider") or str(Path.home() / ".local/bin/aider")
REPO_URL = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

MODELS = {
    "qwen": {
        "label": "Qwen-32B (local)",
        "aider_model": "openai/qwen",
        "api_base": QWEN_API_BASE,
        "api_key": "none",
        "extra_flags": ["--no-verify-ssl", "--no-show-model-warnings"],
    },
    "sonnet": {
        "label": "Sonnet-4.6 (OpenRouter)",
        "aider_model": "openrouter/anthropic/claude-sonnet-4.6",
        "api_base": _OPENROUTER_BASE,
        "api_key": OPENROUTER_API_KEY,
        "extra_flags": [],
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _clone(dest: Path) -> None:
    subprocess.run(["git", "clone", "--depth=1", REPO_URL, str(dest)],
                   check=True, capture_output=True)


def _run_aider(repo: Path, task: dict, model_key: str) -> dict:
    m = MODELS[model_key]
    cmd = [
        AIDER_CMD,
        "--model", m["aider_model"],
        "--openai-api-base", m["api_base"],
        "--openai-api-key", m["api_key"],
        "--no-auto-commits", "--yes",
        "--message", task["prompt"],
        *m["extra_flags"],
        *task.get("allowed_files", []),
    ]
    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=300)
        elapsed = time.monotonic() - t0
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        return {"success": False, "elapsed": 300, "diff": "", "error": "timeout"}

    diff_out = subprocess.run(["git", "diff", "HEAD"],
                              cwd=str(repo), capture_output=True, text=True).stdout
    status_out = subprocess.run(["git", "status", "--porcelain"],
                                cwd=str(repo), capture_output=True, text=True).stdout
    changed = [ln[3:].strip() for ln in status_out.splitlines() if ln.strip()]

    return {
        "success": success,
        "elapsed": round(elapsed, 1),
        "diff": diff_out,
        "changed_files": changed,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-500:],
        "error": None,
    }


def _run_tests(repo: Path) -> dict:
    passed = True
    parts = []
    for cmd, label in [
        (["python3", "-m", "flake8", "--max-line-length=120",
          "--ignore=E501,W503,E241", "."], "flake8"),
        (["python3", "-m", "pytest", "--tb=short", "-q"], "pytest"),
    ]:
        r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=60)
        parts.append(f"[{label} exit={r.returncode}]\n{(r.stdout + r.stderr)[:600]}")
        if r.returncode != 0:
            passed = False
    return {"passed": passed, "output": "\n".join(parts)}


def _judge(task: dict, diff_a: str, diff_b: str, label_a: str, label_b: str) -> dict:
    """Ask GPT-4o-mini to compare two diffs. Returns scores dict."""
    import litellm
    prompt = f"""\
You are a strict code reviewer. Compare two implementations of the same task.

TASK: {task['title']}
SPEC:
{task['prompt']}

--- IMPLEMENTATION A ({label_a}) ---
{diff_a[:3000] or "(no changes made)"}

--- IMPLEMENTATION B ({label_b}) ---
{diff_b[:3000] or "(no changes made)"}

Score each implementation 1-5 on:
- correctness: does it implement the spec exactly?
- quality: clean, idiomatic, no unnecessary code?
- completeness: all parts of the spec addressed?

Respond ONLY with valid JSON, no markdown:
{{
  "a": {{"correctness": N, "quality": N, "completeness": N, "comment": "..."}},
  "b": {{"correctness": N, "quality": N, "completeness": N, "comment": "..."}}
}}
"""
    try:
        resp = litellm.completion(
            model="openrouter/openai/gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            api_base=_OPENROUTER_BASE,
            api_key=OPENROUTER_API_KEY,
            temperature=0.0,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception as e:
        return {"error": str(e)}


# ── Per-model runner (runs in thread) ────────────────────────────────────────

def _run_one(task: dict, model_key: str) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"bench-{model_key}-") as tmp:
        repo = Path(tmp) / "repo"
        _clone(repo)
        aider = _run_aider(repo, task, model_key)
        tests = _run_tests(repo)
        return {
            "model": model_key,
            "label": MODELS[model_key]["label"],
            "elapsed": aider["elapsed"],
            "changed_files": aider.get("changed_files", []),
            "diff": aider["diff"],
            "tests_passed": tests["passed"],
            "test_output": tests["output"],
            "error": aider.get("error"),
        }


# ── Report ───────────────────────────────────────────────────────────────────

def _bool(v: bool) -> str:
    return "✅" if v else "❌"


def _score_line(scores: dict, key: str) -> str:
    a = scores.get("a", {}).get(key, "?")
    b = scores.get("b", {}).get(key, "?")
    return f"{a}/5 vs {b}/5"


def _print_report(task: dict, res_q: dict, res_s: dict, judge: dict) -> None:
    w = 56
    print("\n" + "═" * w)
    print(f"  {task['title']}  [{task['difficulty']}]")
    print("═" * w)
    hdr = f"{'':28} {'Qwen':12} {'Sonnet':12}"
    print(hdr)
    print("-" * w)

    def row(label, a, b):
        print(f"  {label:<26} {str(a):<12} {str(b):<12}")

    row("Tests passed",
        _bool(res_q["tests_passed"]), _bool(res_s["tests_passed"]))
    row("Files changed",
        len(res_q["changed_files"]), len(res_s["changed_files"]))
    row("Time (s)", res_q["elapsed"], res_s["elapsed"])

    if "error" not in judge:
        row("Correctness (judge)", _score_line(judge, "correctness"), "")
        row("Quality (judge)", _score_line(judge, "quality"), "")
        row("Completeness (judge)", _score_line(judge, "completeness"), "")
        print(f"\n  Qwen note:   {judge.get('a', {}).get('comment', '')[:80]}")
        print(f"  Sonnet note: {judge.get('b', {}).get('comment', '')[:80]}")
    else:
        print(f"\n  Judge error: {judge['error']}")

    if res_q.get("error"):
        print(f"\n  ⚠ Qwen error: {res_q['error']}")
    if res_s.get("error"):
        print(f"\n  ⚠ Sonnet error: {res_s['error']}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    filter_id = sys.argv[1] if len(sys.argv) > 1 else None
    tasks = [t for t in TASKS if not filter_id or t["id"] == filter_id]
    if not tasks:
        print(f"No task with id '{filter_id}'")
        sys.exit(1)

    print(f"Running {len(tasks)} task(s) × 2 models in parallel...\n")

    for task in tasks:
        print(f"▶ {task['title']} — running Qwen and Sonnet simultaneously...")
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_q = pool.submit(_run_one, task, "qwen")
            fut_s = pool.submit(_run_one, task, "sonnet")
            res_q = fut_q.result()
            res_s = fut_s.result()

        print("  Both done, asking judge...")
        judge = _judge(task, res_q["diff"], res_s["diff"],
                       res_q["label"], res_s["label"])
        _print_report(task, res_q, res_s, judge)

    print("\n" + "═" * 56)
    print("Done.")


if __name__ == "__main__":
    main()
