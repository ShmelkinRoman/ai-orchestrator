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
]
