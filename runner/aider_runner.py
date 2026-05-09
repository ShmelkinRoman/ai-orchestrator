import logging
import shutil
import subprocess
from pathlib import Path
from config.settings import QWEN_API_BASE

logger = logging.getLogger(__name__)

AIDER_CMD = shutil.which("aider") or str(Path.home() / ".local/bin/aider")


def run(repo_path: str, prompt: str, allowed_files: list[str] | None = None) -> dict:
    """Runs aider with Qwen, returns {success, diff, changed_files}."""
    cmd = [
        AIDER_CMD,
        "--model", "openai/qwen",
        "--openai-api-base", QWEN_API_BASE,
        "--openai-api-key", "none",
        "--no-auto-commits",
        "--yes",
        "--no-verify-ssl",
        "--message", prompt,
    ]
    if allowed_files:
        cmd.extend(allowed_files)

    logger.info("Running aider in %s", repo_path)
    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    stdout = result.stdout
    stderr = result.stderr
    success = result.returncode == 0

    if not success:
        logger.warning("Aider exited %d\nSTDERR: %s", result.returncode, stderr[:500])

    # get diff
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_path, capture_output=True, text=True
    )
    diff = diff_result.stdout

    # get changed files
    files_result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=repo_path, capture_output=True, text=True
    )
    changed = [f for f in files_result.stdout.strip().splitlines() if f]

    return {"success": success, "diff": diff, "changed_files": changed,
            "stdout": stdout, "stderr": stderr}


def commit_changes(repo_path: str, message: str):
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True)


def run_tests(repo_path: str) -> dict:
    """Runs lint, typecheck, pytest. Returns {passed, output}."""
    output_parts = []
    passed = True

    for cmd, label in [
        (["python3", "-m", "flake8", "--max-line-length=120", "--ignore=E501,W503", "."], "flake8"),
        (["python3", "-m", "pytest", "--tb=short", "-q"], "pytest"),
    ]:
        r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        output_parts.append(f"=== {label} (exit {r.returncode}) ===\n{out[:1000]}")
        if r.returncode != 0:
            passed = False

    return {"passed": passed, "output": "\n".join(output_parts)}
