"""Sprint 1.4 extras: invite isolation, expiry, admin deny, resend, me fields."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import hash_token
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header


@pytest.fixture
def bot_service_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-bot-invite-service-token-32c"
    monkeypatch.setenv("BOT_SERVICE_TOKEN", token)
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", token)
    settings.bot_login_rate_limit = 0
    return token


def _bind_bot_company(monkeypatch: pytest.MonkeyPatch, company_id) -> None:
    monkeypatch.setenv("BOT_COMPANY_ID", str(company_id))
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_company_id", str(company_id))
    settings.bot_login_rate_limit = 0


async def _create_invited_employee(
    api_client: AsyncClient,
    admin: Employee,
    company_id,
    *,
    name: str,
) -> tuple[str, str, str]:
    """Returns (employee_id, invite_token, telegram_invite_url|'')."""
    res = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin),
        json={
            "company_id": str(company_id),
            "full_name": name,
            "email": f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}@ex.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    token = body["invite_url"].split("#", 1)[1]
    return body["id"], token, body.get("telegram_invite_url") or ""


@pytest.mark.asyncio
async def test_employee_a_and_b_tokens_differ_and_cross_bind_denied(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_demo_bot")
    _bind_bot_company(monkeypatch, company_a.id)

    emp_a, token_a, url_a = await _create_invited_employee(
        api_client, admin_a, company_a.id, name="Employee A"
    )
    emp_b, token_b, url_b = await _create_invited_employee(
        api_client, admin_a, company_a.id, name="Employee B"
    )
    assert token_a != token_b
    assert url_a != url_b
    assert token_a in url_a and token_b in url_b

    tg_a, tg_b = 9_200_000_001, 9_200_000_002

    ok_a = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token_a,
            "telegram_user_id": tg_a,
            "company_id": str(company_a.id),
        },
    )
    assert ok_a.status_code == 200, ok_a.text
    assert ok_a.json()["employee"]["id"] == emp_a
    assert ok_a.json()["employee"]["telegram_user_id"] == tg_a

    # B's Telegram cannot activate A's invite (already used) / wrong identity.
    deny_b_on_a = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token_a,
            "telegram_user_id": tg_b,
            "company_id": str(company_a.id),
        },
    )
    assert deny_b_on_a.status_code == 400

    ok_b = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token_b,
            "telegram_user_id": tg_b,
            "company_id": str(company_a.id),
        },
    )
    assert ok_b.status_code == 200, ok_b.text
    assert ok_b.json()["employee"]["id"] == emp_b

    # A's Telegram cannot take B's invite (B already activated; A's TG already bound).
    # Fresh invite for C, then A tries C — covered elsewhere. Here: A tries B token (used).
    deny_a_on_b = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token_b,
            "telegram_user_id": tg_a,
            "company_id": str(company_a.id),
        },
    )
    assert deny_a_on_b.status_code == 400
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_expired_telegram_invite_denied(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    _bind_bot_company(monkeypatch, company_a.id)
    _, token, _ = await _create_invited_employee(
        api_client, admin_a, company_a.id, name="Expired Emp"
    )

    async with _uow_factory() as uow:
        await uow.enter_platform()
        invite = await uow.employee_invites.get_by_token_hash(hash_token(token))
        assert invite is not None
        invite.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await uow.commit()

    res = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token,
            "telegram_user_id": 9_200_000_010,
            "company_id": str(company_a.id),
        },
    )
    assert res.status_code == 400
    assert "expired" in res.json()["detail"].lower()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_invite_rejected_via_telegram(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    _bind_bot_company(monkeypatch, company_a.id)
    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "Admin Via TG",
            "email": f"admin-tg-{uuid4().hex[:8]}@example.com",
            "role": "admin",
            "status": "invited",
        },
    )
    assert create.status_code == 201, create.text
    assert create.json()["telegram_invite_url"] is None
    token = create.json()["invite_url"].split("#", 1)[1]

    accept = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token,
            "telegram_user_id": 9_200_000_020,
            "company_id": str(company_a.id),
        },
    )
    assert accept.status_code == 400
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cross_tenant_telegram_invite_denied(
    api_client: AsyncClient,
    company_a,
    company_b,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    # Bot is bound to company B, invite is for company A.
    _bind_bot_company(monkeypatch, company_b.id)
    _, token, _ = await _create_invited_employee(
        api_client, admin_a, company_a.id, name="Cross Tenant"
    )

    res = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token,
            "telegram_user_id": 9_200_000_030,
            "company_id": str(company_b.id),
        },
    )
    assert res.status_code == 400
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_resend_invite_returns_new_telegram_url(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_demo_bot")
    get_settings.cache_clear()

    emp_id, token1, _ = await _create_invited_employee(
        api_client, admin_a, company_a.id, name="Resend Me"
    )
    res = await api_client.post(
        f"/api/v1/employees/{emp_id}/resend-invite",
        headers=auth_header(admin_a),
        json={},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["telegram_invite_url"]
    token2 = body["invite_url"].split("#", 1)[1]
    assert token1 != token2
    assert f"start={token2}" in body["telegram_invite_url"]

    async with _uow_factory() as uow:
        await uow.enter_platform()
        old = await uow.employee_invites.get_by_token_hash(hash_token(token1))
        assert old is not None
        assert old.used_at is not None

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_me_includes_company_and_hired_fields(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    res = await api_client.get(
        "/api/v1/auth/me",
        headers=auth_header(employee_a),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "company_name" in body
    assert "company_description" in body
    assert "hired_at" in body
    assert "telegram_connected" in body
    assert body["role"] == EmployeeRole.EMPLOYEE.value
    assert body["status"] == EmployeeStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_bot_client_invalidate_session_is_targeted() -> None:
    from uuid import uuid4

    from app.bot.api.client import OnboardApiClient

    client = OnboardApiClient(
        base_url="http://example.test",
        company_id=uuid4(),
        service_token="x" * 32,
    )
    client._store_tokens(111, access_token="a1", refresh_token="r1")
    client._store_tokens(222, access_token="a2", refresh_token="r2")
    client.invalidate_session(111)
    assert 111 not in client._token_cache
    assert 222 in client._token_cache
