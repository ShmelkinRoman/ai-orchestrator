"""Post-merge hook: update COMPONENTS.md and reindex changed files in KB."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_INDEXABLE = {".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".java"}


def run(repo_path: str, changed_files: list[str]) -> None:
    """Called after a successful merge. Never raises."""
    try:
        if any(f.endswith(".py") for f in changed_files):
            from runner.components import generate
            generate(repo_path)
    except Exception as exc:
        logger.warning("post_merge_hook: components.generate failed: %s", exc)

    try:
        from config.settings import KB_ENABLED
        if KB_ENABLED:
            from config.settings import GITHUB_REPO
            from agents.indexer import index_file
            for f in changed_files:
                if Path(f).suffix in _INDEXABLE:
                    index_file(repo_path, f, GITHUB_REPO)
    except Exception as exc:
        logger.warning("post_merge_hook: kb indexing failed: %s", exc)
