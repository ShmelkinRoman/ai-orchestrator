import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_CORE_CANDIDATES = [
    "app.py", "main.py", "server.py", "index.py", "api.py",
    "requirements.txt", "package.json", "go.mod", "Cargo.toml",
    "AGENTS.md", "AI_PROJECT_MAP.md",
]

# Test directories / patterns to scan always.
_TEST_DIRS = ["tests", "test", "__tests__", "spec"]


def gather(repo_path: str, keywords: list[str]) -> dict:
    """Collect context: vector KB if KB_ENABLED=true, else grep fallback."""
    from config.settings import KB_ENABLED
    if KB_ENABLED:
        result = _gather_kb(repo_path, keywords)
        if result is not None:
            return result

    return _gather_grep(repo_path, keywords)


def _gather_kb(repo_path: str, keywords: list[str]) -> dict | None:
    """Vector-search based context. Returns None if KB unavailable or empty."""
    try:
        from config.settings import GITHUB_REPO
        from agents.knowledge import search_knowledge

        query = " ".join(keywords)
        chunks = search_knowledge(GITHUB_REPO, query, limit=8)
        if not chunks:
            return None

        file_snippets: dict[str, str] = {}
        for chunk in chunks:
            fp = chunk["file_path"]
            if fp not in file_snippets:
                file_snippets[fp] = chunk["chunk_text"]
            else:
                file_snippets[fp] += "\n...\n" + chunk["chunk_text"]

        root = Path(repo_path)
        components_path = root / "COMPONENTS.md"
        components_md = components_path.read_text(encoding="utf-8") if components_path.exists() else None

        logger.info("KB context: %d chunks from %d files", len(chunks), len(file_snippets))
        return {
            "agents_md": "",
            "project_map": "",
            "relevant_files": list(file_snippets.keys()),
            "file_snippets": file_snippets,
            "components_md": components_md,
        }
    except Exception as e:
        logger.warning("KB gather failed, falling back to grep: %s", e)
        return None


def _gather_grep(repo_path: str, keywords: list[str]) -> dict:
    root = Path(repo_path)

    core_files: dict[str, str] = {}

    # 1. Always read core application files in full.
    for name in _CORE_CANDIDATES:
        p = root / name
        if p.exists():
            core_files[name] = p.read_text()

    # 2. Always read every test file (they define coding patterns).
    test_files: dict[str, str] = {}
    for td in _TEST_DIRS:
        test_dir = root / td
        if test_dir.is_dir():
            for tp in sorted(test_dir.rglob("*.py"))[:10]:
                rel = str(tp.relative_to(root))
                test_files[rel] = tp.read_text()

    # 3. Keyword grep for files not caught above.
    extra_files: list[str] = []
    for kw in keywords:
        if not kw.strip():
            continue
        result = subprocess.run(
            ["grep", "-rl",
             "--include=*.py", "--include=*.ts", "--include=*.js",
             "--include=*.go", "--include=*.java",
             kw, str(root)],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().splitlines():
            rel = line.replace(str(root) + "/", "")
            if rel not in core_files and rel not in test_files and rel not in extra_files:
                extra_files.append(rel)

    extra_snippets: dict[str, str] = {}
    for fp in extra_files[:5]:
        full = root / fp
        if full.exists():
            extra_snippets[fp] = "\n".join(full.read_text().splitlines()[:80])

    agents_md = core_files.pop("AGENTS.md", "")
    project_map = core_files.pop("AI_PROJECT_MAP.md", "")

    components_path = root / "COMPONENTS.md"
    components_md = components_path.read_text(encoding="utf-8") if components_path.exists() else None

    all_snippets = {**core_files, **test_files, **extra_snippets}
    logger.info(
        "Context: %d core, %d test, %d extra files",
        len(core_files), len(test_files), len(extra_snippets),
    )
    return {
        "agents_md": agents_md,
        "project_map": project_map,
        "relevant_files": list(all_snippets.keys()),
        "file_snippets": all_snippets,
        "components_md": components_md,
    }
