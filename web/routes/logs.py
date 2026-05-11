from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.state import get_run_by_id

router = APIRouter()
_templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/logs/{run_id}", response_class=HTMLResponse)
async def run_log(request: Request, run_id: str):
    run = get_run_by_id(run_id)
    return _templates.TemplateResponse("logs.html", {"request": request, "run": run})
