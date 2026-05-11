"""Read and write values in the project .env file."""
import os
import re
from pathlib import Path

ENV_PATH = Path(__file__).parents[1] / ".env"


def get_env_var(key: str) -> str:
    """Read key value directly from .env file (bypasses cached os.environ)."""
    if not ENV_PATH.exists():
        return os.getenv(key, "")
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            val = line[len(key) + 1:]
            # W11: strip inline comment only for unquoted values
            # (quoted values may legitimately contain #, e.g. DB passwords)
            if val[:1] not in ('"', "'"):
                val = re.sub(r"\s+#.*$", "", val)
            return val.strip().strip('"').strip("'")
    return os.getenv(key, "")


def set_env_var(key: str, value: str) -> None:
    """Update key=value in .env file and os.environ."""
    # W12: strip newlines to prevent multi-line injection
    value = value.replace("\n", "").replace("\r", "")
    os.environ[key] = value

    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    text = ENV_PATH.read_text(encoding="utf-8")
    pattern = rf"^{re.escape(key)}=.*$"
    new_line = f"{key}={value}"
    if re.search(pattern, text, re.MULTILINE):
        text = re.sub(pattern, new_line, text, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n{new_line}\n"
    ENV_PATH.write_text(text, encoding="utf-8")
