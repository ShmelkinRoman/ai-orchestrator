import logging
import subprocess
from pathlib import Path
from agents.llm import complete, pick_model

logger = logging.getLogger(__name__)


def run(repo_path: str, changed_files: list[str], spec: str, diff: str):
    root = Path(repo_path)
    model = pick_model("docs")
    prompt = f"""You are a documentation writer.
Given the following changes, update README if public API changed, update CHANGELOG.md, update AI_PROJECT_MAP.md if architecture changed.
Output each file as:
=== FILENAME ===
<full updated content>

Spec summary:
{spec[:1000]}

Changed files: {', '.join(changed_files)}

Diff (truncated):
{diff[:3000]}
"""
    text = complete(model, [{"role": "user", "content": prompt}])
    _apply_doc_updates(root, text)
    logger.info("Docs agent completed")


def _apply_doc_updates(root: Path, text: str):
    sections = text.split("===")
    i = 0
    while i < len(sections) - 1:
        filename = sections[i].strip()
        if filename:
            content = sections[i + 1].strip() if i + 1 < len(sections) else ""
            target = root / filename
            if target.suffix in (".md", ".txt") and ".." not in str(target):
                target.write_text(content + "\n")
                logger.info("Updated doc: %s", filename)
                subprocess.run(["git", "add", str(filename)], cwd=str(root))
        i += 2
