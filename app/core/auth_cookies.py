"""HttpOnly auth cookie helpers for browser sessions."""

from __future__ import annotations

from typing import Literal

from fastapi import Response

from app.core.config import get_settings
from app.schemas.auth import TokenResponse

CookieKind = Literal["tenant", "super_admin"]

ACCESS_COOKIE = "onboard_access"
REFRESH_COOKIE = "onboard_refresh"
SA_ACCESS_COOKIE = "onboard_sa_access"
SA_REFRESH_COOKIE = "onboard_sa_refresh"


def _cookie_names(kind: CookieKind) -> tuple[str, str]:
    if kind == "super_admin":
        return SA_ACCESS_COOKIE, SA_REFRESH_COOKIE
    return ACCESS_COOKIE, REFRESH_COOKIE


def _cookie_common() -> dict:
    settings = get_settings()
    return {
        "httponly": True,
        "secure": settings.is_production,
        "samesite": "lax",
        "path": "/",
    }


def set_auth_cookies(
    response: Response,
    tokens: TokenResponse,
    *,
    kind: CookieKind = "tenant",
) -> None:
    settings = get_settings()
    access_name, refresh_name = _cookie_names(kind)
    common = _cookie_common()
    response.set_cookie(
        key=access_name,
        value=tokens.access_token,
        max_age=settings.access_token_expire_minutes * 60,
        **common,
    )
    response.set_cookie(
        key=refresh_name,
        value=tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        **common,
    )


def clear_auth_cookies(response: Response, *, kind: CookieKind = "tenant") -> None:
    """Delete auth cookies using the same attributes as ``set_auth_cookies``.

    Browsers require matching ``Secure`` / ``HttpOnly`` / ``SameSite`` / ``Path``
    on the clearing ``Set-Cookie`` or production cookies may survive logout.
    """
    access_name, refresh_name = _cookie_names(kind)
    common = _cookie_common()
    for key in (access_name, refresh_name):
        response.delete_cookie(
            key=key,
            path=common["path"],
            secure=common["secure"],
            httponly=common["httponly"],
            samesite=common["samesite"],
        )


def read_refresh_cookie(cookies: dict[str, str], *, kind: CookieKind = "tenant") -> str | None:
    _, refresh_name = _cookie_names(kind)
    return cookies.get(refresh_name)


def read_access_cookie(cookies: dict[str, str], *, kind: CookieKind = "tenant") -> str | None:
    access_name, _ = _cookie_names(kind)
    return cookies.get(access_name)
