import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def gather(repo_path: str, keywords: list[str]) -> dict:
    """Reads AGENTS.md, AI_PROJECT_MAP.md and greps for keywords."""
    root = Path(repo_path)
    agents_md = ""
    project_map = ""

    agents_file = root / "AGENTS.md"
    if agents_file.exists():
        agents_md = agents_file.read_text()

    map_file = root / "AI_PROJECT_MAP.md"
    if map_file.exists():
        project_map = map_file.read_text()

    relevant_files: list[str] = []
    file_snippets: dict[str, str] = {}

    for kw in keywords:
        if not kw.strip():
            continue
        result = subprocess.run(
            ["grep", "-rl", "--include=*.py", "--include=*.ts", "--include=*.js",
             "--include=*.go", "--include=*.java", kw, str(root)],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().splitlines():
            rel = line.replace(str(root) + "/", "")
            if rel not in relevant_files:
                relevant_files.append(rel)

    # read first 60 lines of each relevant file
    for fp in relevant_files[:5]:
        full = root / fp
        if full.exists():
            lines = full.read_text().splitlines()[:60]
            file_snippets[fp] = "\n".join(lines)

    logger.info("Context: found %d relevant files", len(relevant_files))
    return {
        "agents_md": agents_md,
        "project_map": project_map,
        "relevant_files": relevant_files[:10],
        "file_snippets": file_snippets,
    }
