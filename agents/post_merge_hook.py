"""Post-merge hook: update COMPONENTS.md and reindex changed files in KB."""
import logging

logger = logging.getLogger(__name__)


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
            from agents.indexer import reindex_changed
            reindex_changed(repo_path, GITHUB_REPO, "HEAD~1")
    except Exception as exc:
        logger.warning("post_merge_hook: reindex_changed failed: %s", exc)
