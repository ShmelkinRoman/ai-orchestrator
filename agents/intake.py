import json
import logging
from pathlib import Path
from agents.llm import complete, pick_model

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent / "prompts/intake.md").read_text()


def run(issue_body: str) -> dict:
    model = pick_model("intake")
    logger.info("Intake agent running with model %s", model)
    text = complete(
        model,
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
