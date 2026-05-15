"""FastAPI web panel for the AI-SDLC Orchestrator.

Run:  python -m web.main
      (or: uvicorn web.main:app --host 0.0.0.0 --port 8080)
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")  # noqa: E402 must run before app imports

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from web.auth import handle_login, handle_logout, is_session_valid  # noqa: E402
from web.routes import dashboard, issues, logs  # noqa: E402
from web.routes import settings as settings_router  # noqa: E402

app = FastAPI(title="AI Orchestrator", docs_url=None, redoc_url=None)

app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)

_templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# W7: mutating endpoints that must carry HX-Request header
_HTMX_ONLY_PREFIXES = ("/settings/toggle-", "/issues/")


def is_public(path: str) -> bool:
    return path == "/login" or path.startswith("/static")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if not is_public(path):
        # W3: session-based auth (not raw token comparison)
        if os.getenv("WEBUI_TOKEN", "") and not is_session_valid(request):
            return RedirectResponse("/login", status_code=302)

        # W7: CSRF guard — mutating POSTs must come from HTMX
        if request.method == "POST" and any(path.startswith(p) for p in _HTMX_ONLY_PREFIXES):
            if not request.headers.get("HX-Request"):
                return JSONResponse({"detail": "forbidden"}, status_code=403)

    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request):
    return await handle_login(request, _templates)


@app.get("/logout")
async def logout(request: Request):
    return handle_logout(request)


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
