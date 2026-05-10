"""Benchmark tasks — each must be realistic for Qwen as a code executor."""

TASKS = [
    {
        "id": "format_cost",
        "title": "Add format_cost() to cost_log",
        "difficulty": "easy",
        "allowed_files": ["agents/cost_log.py", "tests/test_pipeline.py"],
        "prompt": """\
Edit `agents/cost_log.py` — add this function after the existing imports and before `append_run`:

```python
def format_cost(usd: float) -> str:
    \"\"\"Return a display string for a USD amount, e.g. 0.00423 -> '$0.0042'.\"\"\"
    return f"${usd:.4f}"
```

Edit `tests/test_pipeline.py` — append at the end of the file:

```python
def test_format_cost():
    from agents.cost_log import format_cost
    assert format_cost(0.0) == "$0.0000"
    assert format_cost(0.00423) == "$0.0042"
    assert format_cost(1.5) == "$1.5000"
```
""",
    },
    {
        "id": "version_endpoint",
        "title": "Add GET /version endpoint to app.py",
        "difficulty": "medium",
        "allowed_files": ["app.py", "tests/test_pipeline.py"],
        "prompt": """\
Edit `app.py`:

1. Add this import after `from flask import Flask, jsonify`:
```python
from config.settings import VERSION
```

2. Add this route after the existing `/ping` route:
```python
@app.route('/version', methods=['GET'])
def version():
    return jsonify({"version": VERSION, "status": "ok"})
```

Edit `tests/test_pipeline.py` — append at the end:

```python
def test_version_endpoint():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from app import app
    client = app.test_client()
    resp = client.get('/version')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "version" in data
```
""",
    },
    {
        "id": "aider_timing",
        "title": "Log elapsed time in aider_runner.run()",
        "difficulty": "medium",
        "allowed_files": ["runner/aider_runner.py"],
        "prompt": """\
Edit `runner/aider_runner.py` — in the `run()` function, record and log elapsed time.

Find this existing line:
```python
    logger.info("Running aider in %s", repo_path)
```

Replace it with:
```python
    logger.info("Running aider in %s", repo_path)
    _t0 = time.monotonic()
```

Then find the block that starts with:
```python
    if not success:
        logger.warning("Aider exited %d\nSTDERR: %s", result.returncode, stderr[:500])
```

Add one line before that block:
```python
    logger.info("Aider finished in %.1fs (exit %d)", time.monotonic() - _t0, result.returncode)
```

Also add `import time` at the top of the file if not already present.
No new test needed — the change is observable in logs only.
""",
    },
    {
        "id": "clear_log",
        "title": "Add clear_log() to cost_log",
        "difficulty": "easy",
        "allowed_files": ["agents/cost_log.py", "tests/test_pipeline.py"],
        "prompt": """\
Edit `agents/cost_log.py` — add this function after `total_stats`:

```python
def clear_log(log_path: Path = LOG_PATH) -> None:
    \"\"\"Remove all entries from the log file (truncate to empty).\"\"\"
    if Path(log_path).exists():
        Path(log_path).write_text("", encoding="utf-8")
```

Edit `tests/test_pipeline.py` — append at the end:

```python
def test_clear_log(tmp_path):
    from agents.cost_log import append_run, clear_log, read_recent
    log = tmp_path / "costs.jsonl"
    append_run({"issue": 1, "actual_usd": 0.01}, log_path=log)
    append_run({"issue": 2, "actual_usd": 0.02}, log_path=log)
    assert len(read_recent(10, log_path=log)) == 2
    clear_log(log_path=log)
    assert read_recent(10, log_path=log) == []
```
""",
    },
    {
        "id": "format_summary",
        "title": "Add format_summary() to cost_log",
        "difficulty": "easy",
        "allowed_files": ["agents/cost_log.py", "tests/test_pipeline.py"],
        "prompt": """\
Edit `agents/cost_log.py` — add this function after `total_stats`:

```python
def format_summary(stats: dict) -> str:
    \"\"\"Return a one-line human-readable summary of total_stats() output.

    Example: 'Runs: 5 | Actual: $0.1234 | Sonnet-equiv: $0.5678 | Saved: $0.4444'
    \"\"\"
    return (
        f"Runs: {stats.get('run_count', 0)} | "
        f"Actual: ${stats.get('actual_usd', 0.0):.4f} | "
        f"Sonnet-equiv: ${stats.get('sonnet_eq_usd', 0.0):.4f} | "
        f"Saved: ${stats.get('saved_usd', 0.0):.4f}"
    )
```

Edit `tests/test_pipeline.py` — append at the end:

```python
def test_format_summary():
    from agents.cost_log import format_summary
    stats = {"run_count": 3, "actual_usd": 0.05, "sonnet_eq_usd": 0.9, "saved_usd": 0.85}
    result = format_summary(stats)
    assert "Runs: 3" in result
    assert "$0.0500" in result
    assert "Saved" in result
```
""",
    },
    {
        "id": "slugify_hyphens",
        "title": "Fix _slugify to collapse consecutive hyphens",
        "difficulty": "medium",
        "allowed_files": ["main.py", "tests/test_pipeline.py"],
        "prompt": """\
Edit `main.py` — fix the `_slugify` function.

Currently:
```python
def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text[:40].strip("-")
```

The problem: input like `"hello   world"` produces `"hello-world"` (correct), but
`"feat(ai): add something"` produces `"feat-ai--add-something"` — double hyphens from
the `(` and `)` being replaced separately.

Fix by collapsing consecutive hyphens after the substitution:
```python
def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text[:40].strip("-")
```

Edit `tests/test_pipeline.py` — append at the end:

```python
def test_slugify_no_double_hyphens():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from main import _slugify
    assert _slugify("feat(ai): add something") == "feat-ai-add-something"
    assert _slugify("hello   world") == "hello-world"
    assert _slugify("") == ""
    assert len(_slugify("a" * 100)) <= 40
```
""",
    },
    {
        "id": "triage_keywords",
        "title": "Extend triage medium-risk keywords",
        "difficulty": "easy",
        "allowed_files": ["agents/triage.py", "tests/test_pipeline.py"],
        "prompt": """\
Edit `agents/triage.py` — extend `MEDIUM_KEYWORDS` with four new entries:

Current line:
```python
MEDIUM_KEYWORDS = ["api", "endpoint", "backend", "service", "query", "route"]
```

Replace with:
```python
MEDIUM_KEYWORDS = ["api", "endpoint", "backend", "service", "query", "route",
                   "webhook", "scheduler", "cron", "cache"]
```

Edit `tests/test_pipeline.py` — append at the end:

```python
def test_triage_risk_medium_new_keywords():
    from agents.triage import assess_risk
    for kw in ["webhook", "scheduler", "cron", "cache"]:
        intake = {"title": f"Add {kw} support", "user_story": f"As a user I want {kw}", "risk_hint": "low"}
        assert assess_risk(intake) == "medium", f"Expected medium for keyword '{kw}'"
```
""",
    },
    {
        "id": "run_tests_timeout",
        "title": "Make run_tests() timeout configurable",
        "difficulty": "medium",
        "allowed_files": ["runner/aider_runner.py", "tests/test_pipeline.py"],
        "prompt": """\
Edit `runner/aider_runner.py` — add a `timeout` parameter to `run_tests()`.

Current signature:
```python
def run_tests(repo_path: str) -> dict:
    \"\"\"Runs lint, typecheck, pytest. Returns {passed, output}.\"\"\"
    output_parts = []
    passed = True

    for cmd, label in [
        (["python3", "-m", "flake8", "--max-line-length=120", "--ignore=E501,W503,E241", "."], "flake8"),
        (["python3", "-m", "pytest", "--tb=short", "-q"], "pytest"),
    ]:
        r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=120)
```

Replace with:
```python
def run_tests(repo_path: str, timeout: int = 120) -> dict:
    \"\"\"Runs lint, typecheck, pytest. Returns {passed, output}.\"\"\"
    output_parts = []
    passed = True

    for cmd, label in [
        (["python3", "-m", "flake8", "--max-line-length=120", "--ignore=E501,W503,E241", "."], "flake8"),
        (["python3", "-m", "pytest", "--tb=short", "-q"], "pytest"),
    ]:
        r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=timeout)
```

Edit `tests/test_pipeline.py` — append at the end:

```python
def test_run_tests_accepts_timeout():
    import inspect
    from runner.aider_runner import run_tests
    sig = inspect.signature(run_tests)
    assert "timeout" in sig.parameters
    assert sig.parameters["timeout"].default == 120
```
""",
    },
]
