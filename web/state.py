"""Read shared pipeline state written by the orchestrator."""
import json
from pathlib import Path

COSTS_LOG = Path.home() / ".ai-orch-costs.jsonl"
ACTIVE_FILE = Path.home() / ".ai-orch-active.json"


def get_active_pipelines() -> list[dict]:
    if not ACTIVE_FILE.exists():
        return []
    try:
        return json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


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
