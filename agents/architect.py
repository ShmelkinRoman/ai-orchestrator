import logging
from pathlib import Path
from agents.llm import complete, pick_model, get_role_params

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent / "prompts/architect.md").read_text()


def run(intake_result: dict, triage_result: dict, context: dict) -> str:
    risk = triage_result.get("risk", "low")
    model = pick_model("architect", risk=risk)
    snippets = "\n\n".join(
        f"### {fp}\n```\n{code}\n```"
        for fp, code in context.get("file_snippets", {}).items()
    )
    components_section = context.get("components_md")
    components_block = (
        f"\n\nCOMPONENTS.md (existing public API — do not duplicate):\n{components_section[:6000]}"
        if components_section
        else ""
    )
    user_content = f"""
User story: {intake_result.get('user_story')}

Acceptance criteria:
{chr(10).join('- ' + c for c in intake_result.get('acceptance_criteria', []))}

Risk: {triage_result.get('risk')}

AGENTS.md:
{context.get('agents_md') or '(not found)'}

Relevant files: {', '.join(context.get('relevant_files', [])) or 'none'}

{snippets}{components_block}
"""
    params = get_role_params("architect", risk=risk)
    logger.info("Architect agent running with model %s", model)
    spec = complete(
        model,
        [{"role": "system", "content": _PROMPT}, {"role": "user", "content": user_content.strip()}],
        **params,
    )
    logger.info("Architect spec generated (%d chars)", len(spec))
    return spec


def extract_qwen_prompt(spec: str) -> str:
    lines = spec.splitlines()
    capturing = False
    result_lines = []
    for line in lines:
        if "9." in line and "Qwen prompt" in line:
            capturing = True
            continue
        if capturing:
            if line.strip().startswith("10."):
                break
            result_lines.append(line)
    return "\n".join(result_lines).strip()
