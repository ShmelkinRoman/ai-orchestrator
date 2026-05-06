import json
import logging
from pathlib import Path
from agents.llm import complete
from config.settings import MODELS

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent / "prompts/intake.md").read_text()


def run(issue_body: str) -> dict:
    logger.info("Intake agent running")
    text = complete(
        MODELS["intake_agent"],
        [{"role": "system", "content": _PROMPT}, {"role": "user", "content": issue_body}],
        temperature=0.1,
    )
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    result = json.loads(text)
    logger.info("Intake result: %s", result.get("title"))
    return result
