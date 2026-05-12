"""Simple cookie-based auth for the web panel."""
import hmac
import os
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

_COOKIE = "auth"


def _token() -> str:
    return os.getenv("WEBUI_TOKEN", "")


def is_authenticated(request: Request) -> bool:
    token = _token()
    if not token:
        return True
    return hmac.compare_digest(request.cookies.get(_COOKIE, ""), token)


async def handle_login(request: Request, templates: Jinja2Templates):
    form = await request.form()
    submitted = form.get("token", "")
    if hmac.compare_digest(submitted, _token()):
        resp = RedirectResponse(url="/", status_code=302)
        resp.set_cookie(_COOKIE, submitted, httponly=True, samesite="strict")
        return resp
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Неверный токен"},
        status_code=401,
    )


def handle_logout() -> RedirectResponse:
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(_COOKIE)
    return resp
