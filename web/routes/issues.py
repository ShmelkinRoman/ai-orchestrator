import os
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.issue_tracker import GitHubIssueTracker

router = APIRouter()
_templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")

_issues_cache: dict = {"data": {}, "ts": {}}


def _tracker() -> GitHubIssueTracker:
    return GitHubIssueTracker(
        token=os.getenv("GITHUB_TOKEN", ""),
        repo=os.getenv("GITHUB_REPO", ""),
    )


@router.get("/issues", response_class=HTMLResponse)
async def issues_page(request: Request, label: str = ""):
    cache_key = label
    now = time.time()
    if cache_key in _issues_cache["ts"] and now - _issues_cache["ts"][cache_key] < 60:
        issues = _issues_cache["data"][cache_key]
    else:
        try:
            labels = [label] if label else ["ai-ready", "ai-in-progress"]
            issues = _tracker().get_issues(labels)
        except Exception:
            issues = []
        _issues_cache["data"][cache_key] = issues
        _issues_cache["ts"][cache_key] = now
    return _templates.TemplateResponse("issues.html", {
        "request": request,
        "issues": issues,
        "active_label": label,
    })


@router.post("/issues/{issue_id}/trigger", response_class=HTMLResponse)
async def trigger_issue(request: Request, issue_id: int):
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return HTMLResponse("Forbidden", status_code=403)
    try:
        _tracker().trigger_pipeline(issue_id)
        return HTMLResponse('<span class="text-green-400 text-sm font-medium">Запущен ✓</span>')
    except Exception:
        return HTMLResponse('<span class="text-red-400 text-sm font-medium">Ошибка</span>')
