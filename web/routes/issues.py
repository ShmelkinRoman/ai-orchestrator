import os
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.issue_tracker import GitHubIssueTracker, IssueItem

router = APIRouter()
_templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")

_CACHE_TTL = 60  # seconds

# W6: singleton tracker — avoid re-creating Github client on every request
_tracker_instance: GitHubIssueTracker | None = None
_cache: dict = {"data": [], "ts": 0.0, "labels_key": ""}


def _get_tracker() -> GitHubIssueTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = GitHubIssueTracker(
            token=os.getenv("GITHUB_TOKEN", ""),
            repo=os.getenv("GITHUB_REPO", ""),
        )
    return _tracker_instance


@router.get("/issues", response_class=HTMLResponse)
async def issues_page(request: Request, label: str = ""):
    labels = [label] if label else ["ai-ready", "ai-in-progress"]
    labels_key = ",".join(sorted(labels))
    now = time.monotonic()

    if _cache["labels_key"] == labels_key and now - _cache["ts"] < _CACHE_TTL:
        issues: list[IssueItem] = _cache["data"]
    else:
        try:
            issues = _get_tracker().get_issues(labels)
            _cache.update({"data": issues, "ts": now, "labels_key": labels_key})
        except Exception:
            issues = _cache.get("data", [])

    return _templates.TemplateResponse("issues.html", {
        "request": request,
        "issues": issues,
        "active_label": label,
    })


@router.post("/issues/{issue_id}/trigger", response_class=HTMLResponse)
async def trigger_issue(issue_id: int):
    try:
        _get_tracker().trigger_pipeline(issue_id)
        _cache["ts"] = 0.0  # invalidate cache after trigger
        return HTMLResponse('<span class="text-green-400 text-sm font-medium">Запущен ✓</span>')
    except Exception:
        return HTMLResponse('<span class="text-red-400 text-sm font-medium">Ошибка</span>')
