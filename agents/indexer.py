import ast
import logging
import os
import subprocess
from pathlib import Path

from agents.knowledge import embed_batch, init_db, replace_file_chunks

logger = logging.getLogger(__name__)

_EXTENSIONS = {".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".java"}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", "secrets"}
_SKIP_SUFFIXES = {".tfstate", ".pem", ".key"}
_CHUNK_LINES = 100
_MAX_FILE_BYTES = 100_000


def _should_skip_file(fp: Path) -> bool:
    if fp.name.startswith(".env"):
        return True
    if fp.suffix in _SKIP_SUFFIXES:
        return True
    return False


def _line_chunks(text: str) -> list[str]:
    lines = text.splitlines()
    return [
        "\n".join(lines[i: i + _CHUNK_LINES])
        for i in range(0, len(lines), _CHUNK_LINES)
        if lines[i: i + _CHUNK_LINES]
    ]


def _py_chunks(text: str) -> list[str]:
    """S2: split Python file at top-level function/class boundaries via AST."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _line_chunks(text)

    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    prev_end = 0

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno - 1
        if start > prev_end:
            preamble = "".join(lines[prev_end:start])
            if preamble.strip():
                chunks.append(preamble)
        end = node.end_lineno  # type: ignore[attr-defined]
        node_text = "".join(lines[start:end])
        if node_text.strip():
            chunks.append(node_text)
        prev_end = end

    if prev_end < len(lines):
        tail = "".join(lines[prev_end:])
        if tail.strip():
            chunks.append(tail)

    return chunks if chunks else _line_chunks(text)


def _smart_chunks(text: str, file_path: str) -> list[str]:
    if file_path.endswith(".py"):
        return _py_chunks(text)
    return _line_chunks(text)


def index_file(repo_path: str, file_path: str, project_id: str) -> int:
    """Index one file. Returns number of chunks stored."""
    full = Path(repo_path) / file_path
    if not full.exists():
        return 0
    if full.stat().st_size > _MAX_FILE_BYTES:
        logger.debug("Skipping large file: %s", file_path)
        return 0

    try:
        text = full.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0

    all_chunks = [c for c in _smart_chunks(text, file_path) if c.strip()]
    if not all_chunks:
        return 0

    embeddings = embed_batch(all_chunks)
    if not embeddings or len(embeddings) != len(all_chunks):
        logger.warning("embed_batch returned unexpected result for %s", file_path)
        return 0

    pairs = [(c, e) for c, e in zip(all_chunks, embeddings) if e]
    count = replace_file_chunks(project_id, file_path, pairs)

    if count:
        logger.debug("Indexed %s → %d chunks", file_path, count)
    return count


def index_all(repo_path: str, project_id: str) -> int:
    """Full index of all code files in repo. Returns total chunks stored."""
    if os.getenv("PROJECT_CONFIDENTIAL", "true").lower() == "true":
        logger.warning(
            "index_all skipped: PROJECT_CONFIDENTIAL=true — indexing would send code to OpenRouter"
        )
        return 0

    if not init_db():
        logger.warning("KB not available — skipping index_all")
        return 0

    root = Path(repo_path)
    total = 0
    for fp in sorted(root.rglob("*")):
        if fp.suffix not in _EXTENSIONS:
            continue
        rel = str(fp.relative_to(root))
        if any(part in _SKIP_DIRS for part in fp.parts):
            continue
        if _should_skip_file(fp):
            continue
        total += index_file(repo_path, rel, project_id)

    logger.info("index_all: %d chunks indexed for %s", total, project_id)
    return total


def reindex_changed(repo_path: str, project_id: str, since_commit: str) -> int:
    """Re-index only files changed since given commit SHA."""
    if not init_db():
        logger.warning("KB not available — skipping reindex_changed")
        return 0

    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "diff", "--name-only", since_commit, "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        changed = [
            line for line in result.stdout.strip().splitlines()
            if Path(line).suffix in _EXTENSIONS
        ]
    except Exception as e:
        logger.warning("git diff failed: %s", e)
        return 0

    total = 0
    for rel in changed:
        total += index_file(repo_path, rel, project_id)

    logger.info("reindex_changed: %d chunks from %d files since %s", total, len(changed), since_commit)
    return total
