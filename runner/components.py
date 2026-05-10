"""Generate COMPONENTS.md — a registry of public symbols in the codebase."""
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_SCAN_DIRS = ["agents", "runner", "gh_client", "notifications"]


def generate(repo_path: str) -> bool:
    """Scan repo_path for public Python symbols using ctags and write COMPONENTS.md.

    Returns True on success, False if ctags is unavailable or an error occurs.
    """
    ctags_bin = shutil.which("ctags")
    if not ctags_bin:
        logger.warning("universal-ctags not found; skipping COMPONENTS.md generation")
        return False

    root = Path(repo_path)
    rows: list[tuple[str, str, str]] = []  # (file, kind_label, name)
    kind_map = {"f": "function", "c": "class", "m": "method"}

    for scan_dir in _SCAN_DIRS:
        target = root / scan_dir
        if not target.exists():
            continue
        try:
            result = subprocess.run(
                [ctags_bin, "--recurse", "--fields=+n", "--languages=Python",
                 "--python-kinds=fmc", "-f", "-", str(target)],
                capture_output=True, text=True, check=True, timeout=30,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning("ctags failed for %s: %s", scan_dir, exc)
            return False
        except Exception as exc:
            logger.warning("ctags error for %s: %s", scan_dir, exc)
            return False

        for line in result.stdout.splitlines():
            if line.startswith("!"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name = parts[0]
            if name.startswith("_"):
                continue
            filepath = parts[1]
            kind_char = parts[3] if len(parts) > 3 else ""
            kind_label = kind_map.get(kind_char, kind_char)
            try:
                rel = str(Path(filepath).relative_to(root))
            except ValueError:
                rel = filepath
            rows.append((rel, kind_label, name))

    rows.sort(key=lambda r: (r[0], r[2]))

    lines = [
        "# COMPONENTS.md",
        "",
        "Machine-generated registry of public symbols. **Do not edit manually.**",
        "",
        "| Symbol | Kind | File |",
        "|--------|------|------|",
    ]
    for rel, kind_label, name in rows:
        lines.append(f"| `{name}` | {kind_label} | `{rel}` |")

    output_path = root / "COMPONENTS.md"
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("COMPONENTS.md written with %d entries to %s", len(rows), output_path)
    return True
