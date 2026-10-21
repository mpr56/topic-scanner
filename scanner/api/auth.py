"""Single-user auth: a password login that sets a signed cookie, or a bearer token for scripts."""
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from scanner.api.deps import get_settings_dep
from scanner.api.schemas import LoginIn
from scanner.config import DEFAULT_SESSION_SECRET, Settings

COOKIE = "ts_session"
MAX_AGE = 30 * 24 * 3600

router = APIRouter()


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="session")


def cookies_enabled(settings: Settings) -> bool:
    """With the published default secret anyone could forge a cookie, so only allow it for local http dev."""
    return settings.session_secret != DEFAULT_SESSION_SECRET or not settings.cookie_secure


def _equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def require_auth(request: Request) -> None:
    settings: Settings = request.app.state.settings
    header = request.headers.get("authorization", "")
    if settings.api_token and header.startswith("Bearer ") and _equal(header[7:], settings.api_token):
        return
    cookie = request.cookies.get(COOKIE)
    if cookie and cookies_enabled(settings):
        try:
            _serializer(settings).loads(cookie, max_age=MAX_AGE)
            return
        except BadSignature:
            pass
    raise HTTPException(401, "Not authenticated")


@router.post("/login", status_code=204)
def login(body: LoginIn, settings: Settings = Depends(get_settings_dep)) -> Response:
    if not settings.app_password or not _equal(body.password, settings.app_password):
        raise HTTPException(401, "Wrong password")
    if not cookies_enabled(settings):
        raise HTTPException(503, "SESSION_SECRET is not configured")
    response = Response(status_code=204)
    response.set_cookie(COOKIE, _serializer(settings).dumps("ok"), max_age=MAX_AGE, httponly=True,
                        secure=settings.cookie_secure, samesite="lax", path="/")
    return response


@router.post("/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response
