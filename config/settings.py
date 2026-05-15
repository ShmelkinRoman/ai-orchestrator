import os
from pathlib import Path
from dotenv import load_dotenv
import yaml

load_dotenv(Path(__file__).parent.parent / ".env")

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY")
QWEN_API_BASE = os.getenv("QWEN_API_BASE", "http://100.110.246.46/v1")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")

QWEN_ENABLED = os.getenv("QWEN_ENABLED", "true").lower() == "true"
PROJECT_CONFIDENTIAL = os.getenv("PROJECT_CONFIDENTIAL", "true").lower() == "true"

KB_ENABLED = os.getenv("KB_ENABLED", "false").lower() == "true"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://orchestrator:orchestrator@localhost:5433/ai_orchestrator",
)

_models_path = Path(__file__).parent / "models.yaml"
with open(_models_path) as f:
    MODELS: dict = yaml.safe_load(f)


def _validate_models(models: dict) -> None:
    """Raise RuntimeError if required keys are missing from models.yaml."""
    required_roles = [
        "triage", "intake", "architect_low", "architect_high",
        "developer", "reviewer_low", "reviewer_high", "docs",
    ]
    roles = models.get("roles") or {}
    for role in required_roles:
        val = roles.get(role)
        if val is None:
            raise RuntimeError(f"models.yaml missing required role: roles.{role}")
        # Accept string alias or dict with 'model' key (future-compatible)
        if not isinstance(val, (str, dict)):
            raise RuntimeError(f"models.yaml roles.{role} must be a string or dict, got {type(val)}")
        if isinstance(val, dict) and "model" not in val:
            raise RuntimeError(f"models.yaml roles.{role} dict is missing 'model' key")

    local = models.get("local_developer") or {}
    for key in ("model", "fallback"):
        if not local.get(key):
            raise RuntimeError(f"models.yaml missing required key: local_developer.{key}")

    cheap = models.get("cheap_developer") or {}
    if not cheap.get("model"):
        raise RuntimeError("models.yaml missing required key: cheap_developer.model")


_validate_models(MODELS)

os.environ["OPENROUTER_API_KEY"] = OPENROUTER_API_KEY
VERSION = "0.1.0"

_env_path = Path(__file__).parent.parent / ".env"


def is_qwen_enabled() -> bool:
    """Read QWEN_ENABLED from .env on each call so UI toggles take effect without restart."""
    if _env_path.exists():
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("QWEN_ENABLED="):
                val = line[len("QWEN_ENABLED="):].split("#")[0].strip().strip('"').strip("'")
                return val.lower() == "true"
    return os.getenv("QWEN_ENABLED", "true").lower() == "true"
