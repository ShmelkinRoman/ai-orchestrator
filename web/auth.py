"""Cookie-based auth for the web panel."""
import hmac
import os
import secrets
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

_COOKIE = "auth"

# W3: opaque session IDs — cookie never holds the raw token
_sessions: set[str] = set()


def _token() -> str:
    return os.getenv("WEBUI_TOKEN", "")


def is_session_valid(request: Request) -> bool:
    """Return True if request carries a valid session cookie."""
    token = _token()
    if not token:
        return True  # no token configured → open access
    sid = request.cookies.get(_COOKIE, "")
    return bool(sid and sid in _sessions)


async def handle_login(request: Request, templates: Jinja2Templates):
    form = await request.form()
    submitted = str(form.get("token", ""))
    token = _token()
    # W3: constant-time comparison to prevent timing attacks
    if token and hmac.compare_digest(submitted, token):
        sid = secrets.token_hex(32)
        _sessions.add(sid)
        resp = RedirectResponse(url="/", status_code=302)
        # W3: secure=True on non-localhost; W7: SameSite=strict
        is_secure = request.url.hostname not in ("localhost", "127.0.0.1")
        resp.set_cookie(_COOKIE, sid, httponly=True, samesite="strict", secure=is_secure)
        return resp
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Неверный токен"},
        status_code=401,
    )


def handle_logout(request: Request) -> RedirectResponse:
    sid = request.cookies.get(_COOKIE, "")
    _sessions.discard(sid)
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(_COOKIE)
    return resp
