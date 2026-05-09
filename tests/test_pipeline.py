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
