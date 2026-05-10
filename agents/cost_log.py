"""Persistent cost log for pipeline runs."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".ai-orch-costs.jsonl"


def append_run(record: dict, log_path: Path = LOG_PATH) -> None:
    """Append a run record (dict) as a JSON line to the log file."""
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    logger.debug("Cost log: appended record to %s", log_path)


def read_recent(n: int, log_path: Path = LOG_PATH) -> list:
    """Return the last n entries from the log. Returns [] if file does not exist."""
    if not Path(log_path).exists():
        return []
    with open(log_path, "r", encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    entries = [json.loads(line) for line in lines]
    return entries[-n:]


def total_stats(log_path: Path = LOG_PATH) -> dict:
    """Return aggregated stats over all log entries.

    Returns:
        {
            "run_count": int,
            "actual_usd": float,
            "sonnet_eq_usd": float,
            "saved_usd": float,
        }
    """
    if not Path(log_path).exists():
        return {"run_count": 0, "actual_usd": 0.0, "sonnet_eq_usd": 0.0, "saved_usd": 0.0}
    with open(log_path, "r", encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    entries = [json.loads(line) for line in lines]
    actual = sum(e.get("actual_usd", 0.0) for e in entries)
    sonnet_eq = sum(e.get("sonnet_eq_usd", 0.0) for e in entries)
    return {
        "run_count": len(entries),
        "actual_usd": actual,
        "sonnet_eq_usd": sonnet_eq,
        "saved_usd": sonnet_eq - actual,
    }
