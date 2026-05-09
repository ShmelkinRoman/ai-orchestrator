"""LiteLLM call helper that resolves model aliases to real provider strings."""
import time
import logging
import litellm
from config.settings import MODELS, QWEN_API_BASE, OPENROUTER_API_KEY

logger = logging.getLogger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

_MODEL_MAP = {
    "qwen-local": ("openai/qwen", QWEN_API_BASE, "none"),
    "openrouter/anthropic/claude-sonnet-4-20250514": (
        "openrouter/anthropic/claude-sonnet-4.6",
        _OPENROUTER_BASE,
        OPENROUTER_API_KEY,
    ),
    "openrouter/anthropic/claude-3-5-haiku-20241022": (
        "openrouter/anthropic/claude-haiku-4.5",
        _OPENROUTER_BASE,
        OPENROUTER_API_KEY,
    ),
    "openrouter/openai/gpt-4o-mini": (
        "openrouter/openai/gpt-4o-mini",
        _OPENROUTER_BASE,
        OPENROUTER_API_KEY,
    ),
}

# Fallback for qwen-local when server is down
_QWEN_FALLBACK = ("openrouter/anthropic/claude-haiku-4.5", _OPENROUTER_BASE, OPENROUTER_API_KEY)

_TRANSIENT_ERRORS = (
    litellm.BadGatewayError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.APIConnectionError,
    litellm.Timeout,
)


def _resolve(alias: str) -> tuple[str, str | None, str | None]:
    if alias in _MODEL_MAP:
        return _MODEL_MAP[alias]
    return alias, None, None


def _is_qwen(alias: str) -> bool:
    return alias == "qwen-local"


def complete(alias: str, messages: list[dict], temperature: float = 0.1,
             max_tokens: int = 4096, retries: int = 3) -> str:
    model, api_base, api_key = _resolve(alias)
    kwargs = dict(model=model, messages=messages, temperature=temperature,
                  max_tokens=max_tokens)
    if api_base:
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key
    if api_base and api_base.startswith("https://100."):
        # Self-signed cert on local Tailscale host — skip verification
        kwargs["ssl_verify"] = False

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = litellm.completion(**kwargs)
            return resp.choices[0].message.content.strip()
        except _TRANSIENT_ERRORS as e:
            last_exc = e
            wait = 15 * attempt
            logger.warning(
                "LLM '%s' transient error (attempt %d/%d), retry in %ds: %s",
                alias, attempt, retries, wait, str(e)[:120],
            )
            time.sleep(wait)
        except Exception:
            raise

    # Qwen exhausted — try fallback via OpenRouter
    if _is_qwen(alias):
        logger.warning("Qwen unreachable after %d attempts, using haiku fallback", retries)
        fb_model, fb_base, fb_key = _QWEN_FALLBACK
        resp = litellm.completion(
            model=fb_model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, api_base=fb_base, api_key=fb_key,
        )
        return resp.choices[0].message.content.strip()

    raise last_exc
