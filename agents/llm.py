"""LiteLLM call helper that resolves model aliases to real provider strings."""
import time
import logging
import litellm
from config.settings import MODELS, QWEN_API_BASE, OPENROUTER_API_KEY

# Self-signed cert on Tailscale / local vLLM host — disable SSL verification globally
if QWEN_API_BASE.startswith("https://"):
    litellm.ssl_verify = False

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

# Cost per 1M tokens (input/output) in USD — for comparison reporting
_COST_PER_1M = {
    "openai/qwen":                             (0.0,   0.0),    # local, free
    "openrouter/anthropic/claude-sonnet-4.6":  (3.0,   15.0),
    "openrouter/anthropic/claude-haiku-4.5":   (0.80,  4.0),
    "openrouter/openai/gpt-4o-mini":           (0.15,  0.60),
    # hypothetical: what if Sonnet did this task instead
    "__sonnet_substitute__":                   (3.0,   15.0),
}

# Accumulated cost tracking for current pipeline run
_run_costs: list[dict] = []
_force_haiku: bool = False


def reset_run_costs() -> None:
    _run_costs.clear()


def set_force_haiku(enabled: bool) -> None:
    global _force_haiku
    _force_haiku = enabled
    logger.info("Force-haiku mode: %s", enabled)


def get_run_cost_report() -> dict:
    """Returns actual cost breakdown and hypothetical all-Sonnet cost."""
    actual = 0.0
    sonnet_equivalent = 0.0
    rows = []
    for entry in _run_costs:
        rows.append(entry)
        actual += entry["cost_usd"]
        # what would Sonnet 4.6 cost for same token counts?
        in_p, out_p = _COST_PER_1M["__sonnet_substitute__"]
        sonnet_equivalent += (entry["input_tokens"] * in_p + entry["output_tokens"] * out_p) / 1_000_000

    return {
        "rows": rows,
        "actual_usd": round(actual, 5),
        "sonnet_equivalent_usd": round(sonnet_equivalent, 5),
        "saved_usd": round(sonnet_equivalent - actual, 5),
    }


def _record_cost(alias: str, model: str, input_tokens: int, output_tokens: int) -> float:
    in_p, out_p = _COST_PER_1M.get(model, (0.0, 0.0))
    cost = (input_tokens * in_p + output_tokens * out_p) / 1_000_000
    _run_costs.append({
        "agent": alias, "model": model,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    })
    return cost


def _resolve(alias: str) -> tuple[str, str | None, str | None]:
    if alias in _MODEL_MAP:
        return _MODEL_MAP[alias]
    return alias, None, None


def _is_qwen(alias: str) -> bool:
    return alias == "qwen-local"


def complete(alias: str, messages: list[dict], temperature: float = 0.1,
             max_tokens: int = 4096, retries: int = 3) -> str:
    if _is_qwen(alias) and _force_haiku:
        logger.info("Force-haiku active: routing '%s' → haiku fallback", alias)
        fb_model, fb_base, fb_key = _QWEN_FALLBACK
        resp = litellm.completion(
            model=fb_model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, api_base=fb_base, api_key=fb_key,
        )
        u = resp.usage
        _record_cost(f"{alias}(forced-haiku)", fb_model, u.prompt_tokens, u.completion_tokens)
        return resp.choices[0].message.content.strip()

    model, api_base, api_key = _resolve(alias)
    kwargs = dict(model=model, messages=messages, temperature=temperature,
                  max_tokens=max_tokens)
    if api_base:
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key
    if _is_qwen(alias):
        kwargs["top_p"] = 0.8
        kwargs["extra_body"] = {"repetition_penalty": 1.05}

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = litellm.completion(**kwargs)
            u = resp.usage
            cost = _record_cost(alias, model, u.prompt_tokens, u.completion_tokens)
            logger.info("LLM '%s' tokens in=%d out=%d cost=$%.5f",
                        alias, u.prompt_tokens, u.completion_tokens, cost)
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
        u = resp.usage
        _record_cost(f"{alias}(haiku-fallback)", fb_model, u.prompt_tokens, u.completion_tokens)
        return resp.choices[0].message.content.strip()

    raise last_exc
