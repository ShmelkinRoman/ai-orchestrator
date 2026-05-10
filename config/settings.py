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

_models_path = Path(__file__).parent / "models.yaml"
with open(_models_path) as f:
    MODELS: dict[str, str] = yaml.safe_load(f)

os.environ["OPENROUTER_API_KEY"] = OPENROUTER_API_KEY
VERSION = "0.1.0"
