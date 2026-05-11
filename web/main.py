"""FastAPI web panel for the AI-SDLC Orchestrator.

Run:  python -m web.main
      (or: uvicorn web.main:app --host 0.0.0.0 --port 8080)
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.auth import handle_login, handle_logout
from web.routes import dashboard, issues, logs
from web.routes import settings as settings_router

app = FastAPI(title="AI Orchestrator", docs_url=None, redoc_url=None)

app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)

_templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

def is_public(path: str) -> bool:
    return path == "/login" or path.startswith("/static")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    token = os.getenv("WEBUI_TOKEN", "")
    if token and not is_public(request.url.path):
        if request.cookies.get("auth") != token:
            return RedirectResponse("/login", status_code=302)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request):
    return await handle_login(request, _templates)


@app.get("/logout")
async def logout():
    return handle_logout()


app.include_router(dashboard.router)
app.include_router(settings_router.router)
app.include_router(issues.router)
app.include_router(logs.router)


if __name__ == "__main__":
    import logging
    import uvicorn

    _token = os.getenv("WEBUI_TOKEN", "")
    _host = os.getenv("WEBUI_HOST", "")
    if not _token:
        logging.warning(
            "WEBUI_TOKEN is not set — web panel has no authentication. "
            "Binding to 127.0.0.1 only."
        )
        _host = _host or "127.0.0.1"
    else:
        _host = _host or "0.0.0.0"

    uvicorn.run(
        "web.main:app",
        host=_host,
        port=int(os.getenv("WEBUI_PORT", "8080")),
        reload=False,
    )
