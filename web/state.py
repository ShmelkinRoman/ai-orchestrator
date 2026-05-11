"""Read/write shared pipeline state for the orchestrator and web panel."""
import json
import os
from pathlib import Path

_STATE_DIR = Path(os.getenv("AI_ORCH_STATE_DIR", str(Path.home())))
COSTS_LOG = _STATE_DIR / ".ai-orch-costs.jsonl"
ACTIVE_FILE = _STATE_DIR / ".ai-orch-active.json"


def get_active_pipelines() -> list[dict]:
    if not ACTIVE_FILE.exists():
        return []
    try:
        return json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def write_active(entry: dict) -> None:
    """Upsert pipeline entry (keyed by 'issue'). Safe to call from orchestrator."""
    try:
        entries = [e for e in get_active_pipelines() if e.get("issue") != entry.get("issue")]
        entries.append(entry)
        ACTIVE_FILE.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear_active(issue_number: int) -> None:
    """Remove pipeline entry when it finishes. Safe to call from orchestrator."""
    try:
        entries = [e for e in get_active_pipelines() if e.get("issue") != issue_number]
        ACTIVE_FILE.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_recent_runs(n: int = 10) -> list[dict]:
    if not COSTS_LOG.exists():
        return []
    entries = []
    for line in COSTS_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return list(reversed(entries[-n:]))


def get_run_by_id(run_id: str) -> dict | None:
    if not COSTS_LOG.exists():
        return None
    for line in COSTS_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if str(entry.get("issue")) == run_id or entry.get("run_id") == run_id:
                return entry
        except Exception:
            pass
    return None
