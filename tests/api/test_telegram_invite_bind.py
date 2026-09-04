"""Employee invite → Telegram deep-link bind E2E tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import hash_token
from app.db.enums import EmployeeRole, EmployeeStatus, InvitePurpose
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header, unique_telegram_user_id

pytestmark = [pytest.mark.security, pytest.mark.telegram]


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


@pytest.mark.asyncio
async def test_employee_create_returns_telegram_deep_link(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_demo_bot")
    get_settings.cache_clear()

    response = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "TG Employee",
            "email": f"tg-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invite_email_sent"] is False
    assert body["invite_delivery"] == "manual_url"
    assert "/invite#" in body["invite_url"]
    token = body["invite_url"].split("#", 1)[1]
    assert body["telegram_invite_url"] == (
        f"https://t.me/onboardai_demo_bot?start={token}"
    )
    assert len(token) <= 64
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_telegram_accept_binds_and_marks_invite_used(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_demo_bot")
    _bind_bot_company(monkeypatch, company_a.id)

    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "Bind Me",
            "email": f"bind-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert create.status_code == 201, create.text
    invite_url = create.json()["invite_url"]
    token = invite_url.split("#", 1)[1]
    employee_id = create.json()["id"]
    tg_id = unique_telegram_user_id()

    accept = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token,
            "telegram_user_id": tg_id,
            "telegram_username": "bind_me",
            "company_id": str(company_a.id),
        },
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["employee"]["status"] == EmployeeStatus.ACTIVE.value
    assert accept.json()["employee"]["role"] == EmployeeRole.EMPLOYEE.value
    assert accept.json()["employee"]["telegram_user_id"] == tg_id
    assert "access_token" in accept.json()

    async with _uow_factory() as uow:
        await uow.enter_platform()
        invite = await uow.employee_invites.get_by_token_hash(hash_token(token))
        assert invite is not None
        assert invite.used_at is not None
        emp = await uow.employees.get_by_id(employee_id)
        assert emp is not None
        assert emp.telegram_user_id == tg_id
        assert emp.status == EmployeeStatus.ACTIVE.value

    # Replay rejected
    replay = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token,
            "telegram_user_id": tg_id + 1,
            "company_id": str(company_a.id),
        },
    )
    assert replay.status_code == 400

    # Bot login works after bind
    login = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={"company_id": str(company_a.id), "telegram_user_id": tg_id},
    )
    assert login.status_code == 200, login.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_hr_invite_rejected_via_telegram(
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
            "full_name": "HR Via TG",
            "email": f"hr-tg-{uuid4().hex[:8]}@example.com",
            "role": "hr",
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
            "telegram_user_id": unique_telegram_user_id(),
            "company_id": str(company_a.id),
        },
    )
    assert accept.status_code == 400
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_telegram_cannot_bind_second_employee(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    _bind_bot_company(monkeypatch, company_a.id)
    tg_id = unique_telegram_user_id()

    async def _invite(name: str) -> str:
        res = await api_client.post(
            "/api/v1/employees",
            headers=auth_header(admin_a),
            json={
                "company_id": str(company_a.id),
                "full_name": name,
                "email": f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}@ex.com",
                "role": "employee",
                "status": "invited",
            },
        )
        assert res.status_code == 201, res.text
        return res.json()["invite_url"].split("#", 1)[1]

    token1 = await _invite("First Bind")
    token2 = await _invite("Second Bind")

    first = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token1,
            "telegram_user_id": tg_id,
            "company_id": str(company_a.id),
        },
    )
    assert first.status_code == 200, first.text

    second = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token2,
            "telegram_user_id": tg_id,
            "company_id": str(company_a.id),
        },
    )
    assert second.status_code == 403
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_concurrent_telegram_accept_only_one_wins(
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
            "full_name": "Race Bind",
            "email": f"race-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    token = create.json()["invite_url"].split("#", 1)[1]

    async def _accept(tg: int) -> int:
        res = await api_client.post(
            "/api/v1/auth/bot/invite/accept",
            headers={"X-Bot-Service-Token": bot_service_token},
            json={
                "token": token,
                "telegram_user_id": tg,
                "company_id": str(company_a.id),
            },
        )
        return res.status_code

    codes = await asyncio.gather(
        _accept(unique_telegram_user_id()),
        _accept(unique_telegram_user_id()),
    )
    assert sorted(codes).count(200) == 1
    assert 400 in codes or 403 in codes or codes.count(200) == 1
    assert codes.count(200) == 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_build_telegram_url_requires_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.platform_management import InviteService

    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "")
    get_settings.cache_clear()
    assert (
        InviteService.build_telegram_invite_url(
            purpose=InvitePurpose.EMPLOYEE.value,
            token="abc",
        )
        is None
    )
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@onboardai_demo_bot")
    get_settings.cache_clear()
    url = InviteService.build_telegram_invite_url(
        purpose=InvitePurpose.EMPLOYEE.value,
        token="abcTOKEN",
    )
    assert url == "https://t.me/onboardai_demo_bot?start=abcTOKEN"
    assert (
        InviteService.build_telegram_invite_url(
            purpose=InvitePurpose.HR.value,
            token="abcTOKEN",
        )
        is None
    )
    get_settings.cache_clear()
