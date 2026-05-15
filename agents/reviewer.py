import logging
from pathlib import Path
from agents.llm import complete, pick_model, get_role_params

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent / "prompts/reviewer.md").read_text()


def run(risk: str, issue_body: str, spec: str, diff: str,
        changed_files: list[str], test_output: str) -> dict:
    model = pick_model("reviewer", risk=risk)
    params = get_role_params("reviewer", risk=risk)
    user_content = f"""Issue:
{issue_body}

Technical Spec:
{spec}

Git diff:
```
{diff[:8000]}
```

Changed files: {', '.join(changed_files)}

Test output:
{test_output[:2000]}
"""
    logger.info("Reviewer running with model %s (risk=%s)", model, risk)
    text = complete(
        model,
        [{"role": "system", "content": _PROMPT}, {"role": "user", "content": user_content.strip()}],
        **params,
    )
    return _parse_review(text)


def _parse_review(text: str) -> dict:
    verdict = "REQUEST_CHANGES"
    blockers, should_fix, instructions = [], [], []
    section = None
    for line in text.splitlines():
        ls = line.strip()
        if ls.startswith("VERDICT:"):
            verdict = "APPROVE" if "APPROVE" in ls else "REQUEST_CHANGES"
        elif ls.startswith("BLOCKERS:"):
            section = "blockers"
        elif ls.startswith("SHOULD_FIX:"):
            section = "should_fix"
        elif ls.startswith("INSTRUCTIONS_FOR_QWEN:"):
            section = "instructions"
        elif ls.startswith("- ") and section:
            item = ls[2:]
            if section == "blockers":
                blockers.append(item)
            elif section == "should_fix":
                should_fix.append(item)
            elif section == "instructions":
                instructions.append(item)
    return {"verdict": verdict, "blockers": blockers, "should_fix": should_fix,
            "instructions_for_qwen": instructions, "raw": text}
