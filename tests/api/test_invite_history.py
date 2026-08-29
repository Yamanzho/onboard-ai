"""Invitation history for tenant Admin/HR — metadata only, no secrets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, hash_token
from app.db.enums import EmployeeRole, EmployeeStatus, InvitePurpose, PlatformRole
from app.db.models.employee import Employee
from app.db.models.employee_invite import EmployeeInvite
from app.db.models.super_admin import SuperAdmin
from tests.conftest import _uow_factory, auth_header


def _history_url(employee_id) -> str:
    return f"/api/v1/employees/{employee_id}/invites"


def _assert_no_secrets(body: object) -> None:
    dumped = str(body).lower()
    assert "token_hash" not in dumped
    assert "invite_url" not in dumped
    assert "telegram_invite_url" not in dumped
    assert "/invite#" not in dumped
    if isinstance(body, dict):
        assert "token" not in body
        for item in body.get("items", []):
            assert "token_hash" not in item
            assert "token" not in item
            assert "invite_url" not in item
            assert "telegram_invite_url" not in item


async def _create_invited(
    api_client: AsyncClient,
    *,
    company_id,
    actor: Employee,
    role: str = EmployeeRole.EMPLOYEE.value,
    email: str | None = None,
) -> dict:
    response = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(actor),
        json={
            "company_id": str(company_id),
            "full_name": f"Invited {role}",
            "email": email or f"inv-{uuid4().hex[:8]}@example.com",
            "role": role,
            "status": "invited",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _insert_invite(
    *,
    company_id,
    employee_id,
    purpose: str,
    expires_at: datetime,
    used_at: datetime | None = None,
    email: str = "hist@example.com",
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_id,
                employee_id=employee_id,
                token_hash=hash_token(f"hist-{uuid4().hex}"),
                expires_at=expires_at,
                used_at=used_at,
                invited_email=email,
                purpose=purpose,
            ),
        )
        await uow.commit()


@pytest.mark.asyncio
async def test_admin_can_list_employee_invitations(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    created = await _create_invited(
        api_client, company_id=company_a.id, actor=admin_a
    )
    response = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(admin_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_no_secrets(body)
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["status"] == "active"
    assert item["purpose"] == InvitePurpose.EMPLOYEE.value
    assert item["invited_email"] == created["email"]
    assert item["used_at"] is None
    assert item["created_at"]
    assert item["expires_at"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_hr_can_list_allowed_employee_invitations(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    hr_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    created = await _create_invited(
        api_client, company_id=company_a.id, actor=admin_a
    )
    response = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(hr_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_no_secrets(body)
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "active"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_company_a_cannot_list_company_b_invitations(
    api_client: AsyncClient,
    company_b,
    admin_a: Employee,
    admin_b: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    created = await _create_invited(
        api_client, company_id=company_b.id, actor=admin_b
    )
    response = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(admin_a),
    )
    assert response.status_code == 404, response.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_employee_cannot_list_invitation_history(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    employee_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    created = await _create_invited(
        api_client, company_id=company_a.id, actor=admin_a
    )
    response = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(employee_a),
    )
    assert response.status_code == 403, response.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_password_reset_invites_are_excluded(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    created = await _create_invited(
        api_client, company_id=company_a.id, actor=admin_a
    )
    await _insert_invite(
        company_id=company_a.id,
        employee_id=created["id"],
        purpose=InvitePurpose.PASSWORD_RESET.value,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        email=created["email"],
    )
    response = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(admin_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_no_secrets(body)
    purposes = {item["purpose"] for item in body["items"]}
    assert InvitePurpose.PASSWORD_RESET.value not in purposes
    assert purposes == {InvitePurpose.EMPLOYEE.value}
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_active_expired_and_used_invite_statuses(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    now = datetime.now(UTC)
    await _insert_invite(
        company_id=company_a.id,
        employee_id=employee_a.id,
        purpose=InvitePurpose.EMPLOYEE.value,
        expires_at=now + timedelta(hours=12),
        email="active@example.com",
    )
    await _insert_invite(
        company_id=company_a.id,
        employee_id=employee_a.id,
        purpose=InvitePurpose.EMPLOYEE.value,
        expires_at=now - timedelta(hours=2),
        email="expired@example.com",
    )
    await _insert_invite(
        company_id=company_a.id,
        employee_id=employee_a.id,
        purpose=InvitePurpose.EMPLOYEE.value,
        expires_at=now + timedelta(hours=12),
        used_at=now - timedelta(minutes=5),
        email="used@example.com",
    )
    response = await api_client.get(
        _history_url(employee_a.id),
        headers=auth_header(admin_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_no_secrets(body)
    by_email = {item["invited_email"]: item["status"] for item in body["items"]}
    assert by_email["active@example.com"] == "active"
    assert by_email["expired@example.com"] == "expired"
    assert by_email["used@example.com"] == "used"


@pytest.mark.asyncio
async def test_resend_creates_history_row_and_returns_new_url(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    created = await _create_invited(
        api_client, company_id=company_a.id, actor=admin_a
    )
    first_url = created["invite_url"]
    assert first_url and "/invite#" in first_url

    resend = await api_client.post(
        f"/api/v1/employees/{created['id']}/resend-invite",
        headers=auth_header(admin_a),
        json={},
    )
    assert resend.status_code == 200, resend.text
    new_url = resend.json()["invite_url"]
    assert new_url and "/invite#" in new_url
    assert new_url != first_url

    history = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(admin_a),
    )
    assert history.status_code == 200, history.text
    items = history.json()["items"]
    _assert_no_secrets(history.json())
    assert len(items) == 2
    assert items[0]["status"] == "active"
    assert items[1]["status"] == "used"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_web_invite_acceptance_still_works_after_history(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    created = await _create_invited(
        api_client, company_id=company_a.id, actor=admin_a
    )
    listed = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(admin_a),
    )
    assert listed.status_code == 200
    token = created["invite_url"].split("#", 1)[1]
    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": "SecurePass1!"},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == EmployeeStatus.ACTIVE.value

    history = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(admin_a),
    )
    assert history.status_code == 200
    assert history.json()["items"][0]["status"] == "used"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_telegram_invite_acceptance_still_works_after_history(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_token = "test-bot-invite-history-token-32c"
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("BOT_SERVICE_TOKEN", bot_token)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_demo_bot")
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", bot_token)
    settings.bot_login_rate_limit = 0

    created = await _create_invited(
        api_client, company_id=company_a.id, actor=admin_a
    )
    listed = await api_client.get(
        _history_url(created["id"]),
        headers=auth_header(admin_a),
    )
    assert listed.status_code == 200
    token = created["invite_url"].split("#", 1)[1]
    tg_id = 9_100_000_042
    accept = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_token},
        json={
            "token": token,
            "telegram_user_id": tg_id,
            "telegram_username": "hist_bind",
        },
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["employee"]["status"] == EmployeeStatus.ACTIVE.value
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invalid_employee_id_returns_not_found(
    api_client: AsyncClient,
    admin_a: Employee,
) -> None:
    response = await api_client.get(
        _history_url(uuid4()),
        headers=auth_header(admin_a),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_super_admin_token_cannot_use_tenant_invite_history(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    created = await _create_invited(
        api_client, company_id=company_a.id, actor=admin_a
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        sa = await uow.super_admins.create(
            SuperAdmin(
                email=f"sa-hist-{uuid4().hex[:8]}@test.local",
                full_name="History Super Admin",
                password_hash=hash_password("unused-sa-pass"),
                is_active=True,
            ),
        )
        await uow.commit()
    sa_headers = {
        "Authorization": (
            "Bearer "
            + create_access_token(
                subject=sa.id,
                role=PlatformRole.SUPER_ADMIN.value,
                company_id=None,
            )
        )
    }
    response = await api_client.get(
        _history_url(created["id"]),
        headers=sa_headers,
    )
    assert response.status_code == 401
    get_settings.cache_clear()
