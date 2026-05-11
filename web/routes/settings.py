import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.env_editor import get_env_var, set_env_var

router = APIRouter()
_templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    qwen_enabled = get_env_var("QWEN_ENABLED").lower() == "true"
    confidential = get_env_var("PROJECT_CONFIDENTIAL").lower() == "true"
    api_keys = {
        "OpenRouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "GitHub": bool(os.getenv("GITHUB_TOKEN")),
        "Telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
    }
    return _templates.TemplateResponse("settings.html", {
        "request": request,
        "qwen_enabled": qwen_enabled,
        "deepseek_enabled": not confidential,
        "api_keys": api_keys,
    })


@router.post("/settings/toggle-qwen", response_class=HTMLResponse)
async def toggle_qwen(request: Request):
    current = get_env_var("QWEN_ENABLED").lower() == "true"
    enabled = not current
    set_env_var("QWEN_ENABLED", "true" if enabled else "false")
    return HTMLResponse(_toggle_html("qwen-toggle", "/settings/toggle-qwen", enabled))


@router.post("/settings/toggle-deepseek", response_class=HTMLResponse)
async def toggle_deepseek(request: Request):
    confidential = get_env_var("PROJECT_CONFIDENTIAL").lower() == "true"
    new_confidential = not confidential
    set_env_var("PROJECT_CONFIDENTIAL", "true" if new_confidential else "false")
    enabled = not new_confidential
    return HTMLResponse(_toggle_html("deepseek-toggle", "/settings/toggle-deepseek", enabled))


def _toggle_html(div_id: str, endpoint: str, enabled: bool) -> str:
    bg = "bg-indigo-600" if enabled else "bg-gray-700"
    translate = "translate-x-6" if enabled else "translate-x-1"
    return (
        f'<div id="{div_id}">'
        f'<button hx-post="{endpoint}" hx-target="#{div_id}" hx-swap="outerHTML" '
        f'class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors {bg}">'
        f'<span class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform {translate}"></span>'
        f"</button></div>"
    )
