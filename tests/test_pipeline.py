"""Basic smoke tests for the orchestrator components."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_intake_prompt_exists():
    from pathlib import Path
    p = Path(__file__).parent.parent / "prompts/intake.md"
    assert p.exists()
    assert "Output JSON only" in p.read_text()


def test_triage_risk_high():
    from agents.triage import assess_risk
    intake = {"title": "Fix authentication bug", "user_story": "As a user...", "risk_hint": "low"}
    assert assess_risk(intake) == "high"


def test_triage_risk_medium():
    from agents.triage import assess_risk
    intake = {"title": "Add API endpoint", "user_story": "As a developer I want api endpoint", "risk_hint": "low"}
    assert assess_risk(intake) == "medium"


def test_triage_risk_low():
    from agents.triage import assess_risk
    intake = {"title": "Update button color", "user_story": "As a user I want button to be blue", "risk_hint": "low"}
    assert assess_risk(intake) == "low"


def test_review_parse_approve():
    from agents.reviewer import _parse_review
    text = "VERDICT: APPROVE\nBLOCKERS:\n- none\nSHOULD_FIX:\nINSTRUCTIONS_FOR_QWEN:\n"
    result = _parse_review(text)
    assert result["verdict"] == "APPROVE"


def test_review_parse_request_changes():
    from agents.reviewer import _parse_review
    text = "VERDICT: REQUEST_CHANGES\nBLOCKERS:\n- Missing error handling\nSHOULD_FIX:\n- Add validation\nINSTRUCTIONS_FOR_QWEN:\n- Add try/except\n"
    result = _parse_review(text)
    assert result["verdict"] == "REQUEST_CHANGES"
    assert "Missing error handling" in result["blockers"]
    assert "Add try/except" in result["instructions_for_qwen"]


def test_architect_extract_qwen_prompt():
    from agents.architect import extract_qwen_prompt
    spec = """1. Summary\nBla bla\n2. Risk: low\n...\n9. Qwen prompt:\nAdd a health endpoint to app.py\n10. Reviewer checklist:\n- Check status code"""
    prompt = extract_qwen_prompt(spec)
    assert "health endpoint" in prompt


def test_settings_loaded():
    from config import settings
    assert settings.GITHUB_REPO


def test_models_yaml():
    from config.settings import MODELS
    assert "intake_agent" in MODELS
    assert "architect_agent" in MODELS
    assert "reviewer_high" in MODELS


def test_cost_log_append_run(tmp_path):
    from agents.cost_log import append_run
    log_file = tmp_path / "costs.jsonl"
    record = {"issue": 1, "actual_usd": 0.01, "sonnet_eq_usd": 0.05}
    append_run(record, log_path=log_file)
    assert log_file.exists()
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1


def test_cost_log_jsonl_format(tmp_path):
    import json
    from agents.cost_log import append_run
    log_file = tmp_path / "costs.jsonl"
    append_run({"issue": 1, "actual_usd": 0.01, "sonnet_eq_usd": 0.05}, log_path=log_file)
    append_run({"issue": 2, "actual_usd": 0.02, "sonnet_eq_usd": 0.10}, log_path=log_file)
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert "issue" in entry
        assert "actual_usd" in entry
        assert "sonnet_eq_usd" in entry


def test_cost_log_total_stats(tmp_path):
    from agents.cost_log import append_run, total_stats
    log_file = tmp_path / "costs.jsonl"
    append_run({"issue": 1, "actual_usd": 0.01, "sonnet_eq_usd": 0.05}, log_path=log_file)
    append_run({"issue": 2, "actual_usd": 0.02, "sonnet_eq_usd": 0.10}, log_path=log_file)
    stats = total_stats(log_path=log_file)
    assert stats["run_count"] == 2
    assert abs(stats["actual_usd"] - 0.03) < 1e-9
    assert abs(stats["sonnet_eq_usd"] - 0.15) < 1e-9
    assert abs(stats["saved_usd"] - 0.12) < 1e-9


def test_cost_log_read_recent(tmp_path):
    from agents.cost_log import append_run, read_recent
    log_file = tmp_path / "costs.jsonl"
    append_run({"issue": 1, "actual_usd": 0.01, "sonnet_eq_usd": 0.05}, log_path=log_file)
    append_run({"issue": 2, "actual_usd": 0.02, "sonnet_eq_usd": 0.10}, log_path=log_file)
    append_run({"issue": 3, "actual_usd": 0.03, "sonnet_eq_usd": 0.15}, log_path=log_file)
    recent = read_recent(2, log_path=log_file)
    assert len(recent) == 2
    assert recent[0]["issue"] == 2
    assert recent[1]["issue"] == 3


def test_version_constant():
    from config.settings import VERSION
    assert VERSION == "0.1.0"
