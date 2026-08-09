"""P2.1: cookie-only browser auth and production cookie delete attributes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import Response
from httpx import AsyncClient
from starlette.datastructures import MutableHeaders

from app.core.auth_cookies import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    SA_ACCESS_COOKIE,
    SA_REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.enums import PlatformRole
from app.db.models.employee import Employee
from app.db.models.super_admin import SuperAdmin
from app.db.uow import UnitOfWork
from app.schemas.auth import TokenResponse
from tests.conftest import (
    sa_tokens_from_response,
    tenant_tokens_from_response,
)


def _set_cookie_header_values(response: Response) -> list[str]:
    headers = MutableHeaders(scope={"type": "http", "headers": []})
    # Starlette Response stores raw set-cookie entries in raw_headers.
    values: list[str] = []
    for key, value in response.raw_headers:
        if key.lower() == b"set-cookie":
            values.append(value.decode("latin-1"))
    return values


def test_clear_auth_cookies_matches_production_set_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    assert settings.is_production is True

    response = Response()
    set_auth_cookies(
        response,
        TokenResponse(access_token="access-value", refresh_token="refresh-value"),
        kind="tenant",
    )
    set_headers = _set_cookie_header_values(response)
    assert any(ACCESS_COOKIE in h and "Secure" in h for h in set_headers)
    assert any(REFRESH_COOKIE in h and "HttpOnly" in h for h in set_headers)
    assert any("SameSite=lax" in h or "SameSite=Lax" in h for h in set_headers)

    clear_auth_cookies(response, kind="tenant")
    clear_headers = _set_cookie_header_values(response)
    # Clearing Set-Cookie entries must also carry Secure/HttpOnly/SameSite in production.
    cleared_access = [h for h in clear_headers if h.startswith(f"{ACCESS_COOKIE}=")]
    cleared_refresh = [h for h in clear_headers if h.startswith(f"{REFRESH_COOKIE}=")]
    assert cleared_access, clear_headers
    assert cleared_refresh, clear_headers
    for header in (*cleared_access[-1:], *cleared_refresh[-1:]):
        assert "Secure" in header
        assert "HttpOnly" in header
        assert "SameSite=lax" in header or "SameSite=Lax" in header
        assert "Path=/" in header


def test_clear_sa_auth_cookies_matches_production_set_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")

    response = Response()
    set_auth_cookies(
        response,
        TokenResponse(access_token="sa-access", refresh_token="sa-refresh"),
        kind="super_admin",
    )
    clear_auth_cookies(response, kind="super_admin")
    clear_headers = _set_cookie_header_values(response)
    for name in (SA_ACCESS_COOKIE, SA_REFRESH_COOKIE):
        matching = [h for h in clear_headers if h.startswith(f"{name}=")]
        assert matching, clear_headers
        header = matching[-1]
        assert "Secure" in header
        assert "HttpOnly" in header
        assert "SameSite=lax" in header or "SameSite=Lax" in header


async def test_browser_login_and_refresh_are_cookie_only(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    settings = get_settings()
    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(admin_a.id), "password": settings.auth_password},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body == {"token_type": "bearer"}
    assert "access_token" not in body
    assert "refresh_token" not in body
    tenant_tokens_from_response(login)

    # Cookie flags on browser login Set-Cookie (dev: no Secure).
    set_cookie = login.headers.get_list("set-cookie")
    assert any(ACCESS_COOKIE in c and "HttpOnly" in c for c in set_cookie)
    assert any(REFRESH_COOKIE in c and "HttpOnly" in c for c in set_cookie)
    assert any("SameSite=lax" in c or "SameSite=Lax" in c for c in set_cookie)

    # Browser refresh (empty body / cookie) must not expose tokens.
    browser_refresh = await api_client.post("/api/v1/auth/refresh", json={})
    assert browser_refresh.status_code == 200, browser_refresh.text
    refresh_body = browser_refresh.json()
    assert refresh_body == {"token_type": "bearer"}
    assert "access_token" not in refresh_body
    assert "refresh_token" not in refresh_body

    # Fresh login + service-mode refresh still returns JSON pair for bots.
    login2 = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(admin_a.id), "password": settings.auth_password},
    )
    fresh = tenant_tokens_from_response(login2)
    service_refresh = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": fresh["refresh_token"]},
    )
    assert service_refresh.status_code == 200, service_refresh.text
    assert service_refresh.json()["access_token"]
    assert service_refresh.json()["refresh_token"]
    assert service_refresh.json()["refresh_token"] != fresh["refresh_token"]


async def test_bot_login_still_returns_json_tokens(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "test-bot-service-token-p21"
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", token)
    monkeypatch.setattr(settings, "bot_company_id", str(company_a.id))

    res = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers={"X-Bot-Service-Token": token},
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": employee_a.telegram_user_id,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_super_admin_browser_login_refresh_cookie_only(
    api_client: AsyncClient,
) -> None:
    password = "SuperAdminP21!"
    suffix = uuid4().hex[:8]
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        admin = await uow.super_admins.create(
            SuperAdmin(
                email=f"sa-p21-{suffix}@test.local",
                full_name="SA P21",
                password_hash=hash_password(password),
                is_active=True,
            ),
        )
        await uow.commit()

    login = await api_client.post(
        "/api/v1/super-admin/auth/login",
        json={"email": admin.email, "password": password},
    )
    assert login.status_code == 200, login.text
    assert login.json() == {"token_type": "bearer"}
    assert "access_token" not in login.json()
    tokens = sa_tokens_from_response(login)

    browser_refresh = await api_client.post(
        "/api/v1/super-admin/auth/refresh",
        json={},
    )
    assert browser_refresh.status_code == 200, browser_refresh.text
    assert browser_refresh.json() == {"token_type": "bearer"}
    assert "access_token" not in browser_refresh.json()

    # Cookie session still authenticates /me
    me = await api_client.get(
        "/api/v1/super-admin/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == PlatformRole.SUPER_ADMIN.value


async def test_logout_clears_cookies(
    api_client: AsyncClient,
    admin_a: Employee,
) -> None:
    settings = get_settings()
    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(admin_a.id), "password": settings.auth_password},
    )
    assert login.status_code == 200
    refresh = tenant_tokens_from_response(login)["refresh_token"]

    logout = await api_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh},
    )
    assert logout.status_code == 204
    set_cookie = logout.headers.get_list("set-cookie")
    assert any(c.startswith(f"{ACCESS_COOKIE}=") for c in set_cookie)
    assert any(c.startswith(f"{REFRESH_COOKIE}=") for c in set_cookie)

    # Cleared cookies should not authenticate /me via cookie jar leftovers alone
    # after explicit expire; verify refresh of old token fails.
    replay = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert replay.status_code == 401


async def test_refresh_rotation_unchanged_with_service_mode(
    api_client: AsyncClient,
    admin_a: Employee,
) -> None:
    settings = get_settings()
    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(admin_a.id), "password": settings.auth_password},
    )
    old_refresh = tenant_tokens_from_response(login)["refresh_token"]

    rotated = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert rotated.status_code == 200
    new_refresh = rotated.json()["refresh_token"]
    assert new_refresh != old_refresh

    replay = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert replay.status_code == 401
    assert "reuse" in replay.json()["detail"].lower()

    after_reuse = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_refresh},
    )
    assert after_reuse.status_code == 401
