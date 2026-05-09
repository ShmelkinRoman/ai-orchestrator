import logging

logger = logging.getLogger(__name__)

HIGH_KEYWORDS = ["auth", "authentication", "payment", "billing", "migration", "security", "password", "secret", "token", "db", "database"]
MEDIUM_KEYWORDS = ["api", "endpoint", "backend", "service", "query", "route"]


def assess_risk(intake_result: dict, relevant_files: list[str] | None = None) -> str:
    title = (intake_result.get("title") or "").lower()
    story = (intake_result.get("user_story") or "").lower()
    hint = intake_result.get("risk_hint", "low")
    combined = title + " " + story

    if any(kw in combined for kw in HIGH_KEYWORDS):
        risk = "high"
    elif any(kw in combined for kw in MEDIUM_KEYWORDS):
        risk = "medium"
    elif relevant_files and len(relevant_files) > 3:
        risk = "medium"
    else:
        risk = hint or "low"

    logger.info("Triage risk: %s", risk)
    return risk


def run(intake_result: dict, relevant_files: list[str] | None = None) -> dict:
    risk = assess_risk(intake_result, relevant_files)
    needs_clarification = intake_result.get("needs_clarification", False)
    questions = intake_result.get("clarification_questions", [])
    return {
        "risk": risk,
        "needs_clarification": needs_clarification,
        "clarification_questions": questions,
    }
