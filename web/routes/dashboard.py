import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from agents.cost_log import total_stats
from web.state import get_active_pipelines, get_recent_runs

router = APIRouter()
_templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return _templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active": get_active_pipelines(),
        "recent": get_recent_runs(10),
        "stats": total_stats(),
        "qwen_enabled": os.getenv("QWEN_ENABLED", "true").lower() == "true",
        "api_ok": bool(os.getenv("OPENROUTER_API_KEY")),
    })
