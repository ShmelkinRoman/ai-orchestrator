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
            raw = line[len(key) + 1:]
            # Quoted value: find matching closing quote, ignore # inside
            if raw[:1] in ('"', "'"):
                quote = raw[0]
                end = raw.find(quote, 1)
                return raw[1:end] if end != -1 else raw[1:]
            # Unquoted: strip inline comment (only space-hash counts as comment delimiter)
            raw = re.sub(r"\s+#.*$", "", raw)
            return raw.strip()
    return os.getenv(key, "")


def set_env_var(key: str, value: str) -> None:
    """Update key=value in .env file and os.environ."""
    if "\n" in value or "\r" in value:
        raise ValueError("env value must not contain newlines")

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
