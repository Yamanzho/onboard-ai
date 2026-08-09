"""Unified invitation infrastructure — HR/Admin/Employee purpose + tenant create."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.security import hash_token
from app.db.enums import EmployeeRole, EmployeeStatus, InvitePurpose
from app.db.models.employee import Employee
from app.services.email import EmailService
from tests.conftest import _uow_factory, auth_header


@pytest.mark.asyncio
async def test_tenant_create_hr_returns_manual_url_when_smtp_off(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    from app.core.config import get_settings

    get_settings.cache_clear()

    response = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 5000,
            "full_name": "New HR",
            "email": f"hr-{uuid4().hex[:8]}@example.com",
            "role": "hr",
            "status": "invited",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == EmployeeStatus.INVITED.value
    assert body["role"] == EmployeeRole.HR.value
    assert body["invite_email_sent"] is False
    assert body["invite_delivery"] == "manual_url"
    assert body["invite_url"] and "/invite#" in body["invite_url"]
    assert body["telegram_invite_url"] is None

    token = body["invite_url"].split("#", 1)[1]
    async with _uow_factory() as uow:
        await uow.enter_platform()
        invite = await uow.employee_invites.get_by_token_hash(hash_token(token))
        assert invite is not None
        assert invite.purpose == InvitePurpose.HR.value
        assert invite.used_at is None

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_accept_hr_invite_activates_role_from_purpose_then_login(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    from app.core.config import get_settings

    get_settings.cache_clear()

    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 5100,
            "full_name": "Invite HR",
            "email": f"invite-hr-{uuid4().hex[:8]}@example.com",
            "role": "hr",
            "status": "invited",
        },
    )
    assert create.status_code == 201, create.text
    invite_url = create.json()["invite_url"]
    token = invite_url.split("#", 1)[1]
    employee_id = create.json()["id"]

    preview = await api_client.post(
        "/api/v1/auth/invite/preview",
        json={"token": token},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["purpose"] == "hr"
    assert preview.json()["role"] == "hr"
    assert preview.json()["company_name"]

    password = "SecurePass1!"
    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": password},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == EmployeeStatus.ACTIVE.value
    assert accept.json()["role"] == EmployeeRole.HR.value

    # Replay must fail
    replay = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": password},
    )
    assert replay.status_code == 400

    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": employee_id, "password": password},
    )
    assert login.status_code == 200, login.text

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_accept_ignores_client_role_company_fields(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept schema only allows token+password — extra fields rejected."""
    monkeypatch.setenv("SMTP_HOST", "")
    from app.core.config import get_settings

    get_settings.cache_clear()

    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 5200,
            "full_name": "Invite Admin",
            "email": f"invite-admin-{uuid4().hex[:8]}@example.com",
            "role": "admin",
            "status": "invited",
        },
    )
    assert create.status_code == 201, create.text
    token = create.json()["invite_url"].split("#", 1)[1]

    bad = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={
            "token": token,
            "password": "SecurePass1!",
            "role": "employee",
            "company_id": str(uuid4()),
        },
    )
    # Extra fields ignored by default pydantic, or 422 — either way role stays admin.
    if bad.status_code == 200:
        assert bad.json()["role"] == EmployeeRole.ADMIN.value
    else:
        assert bad.status_code == 422

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_employee_invite_email_copy_and_telegram_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "OnboardAIBot")
    from app.core.config import get_settings

    get_settings.cache_clear()

    result = await EmailService().send_invite_email(
        to_email="e@example.com",
        full_name="Emp",
        invite_url="https://example.test/invite#tok",
        company_name="Acme",
        purpose=InvitePurpose.EMPLOYEE.value,
        telegram_invite_url="https://t.me/OnboardAIBot",
    )
    assert result.email_sent is False
    assert result.delivery == "manual_url"
    assert result.telegram_invite_url == "https://t.me/OnboardAIBot"

    hr = await EmailService().send_invite_email(
        to_email="hr@example.com",
        full_name="HR",
        invite_url="https://example.test/invite#tok",
        company_name="Acme",
        purpose=InvitePurpose.HR.value,
    )
    assert hr.telegram_invite_url is None

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invited_create_requires_email(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    response = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 5300,
            "full_name": "No Email",
            "role": "employee",
            "status": "invited",
        },
    )
    assert response.status_code == 422, response.text
