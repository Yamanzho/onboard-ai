"""Security regression tests for auth, tenancy, and RBAC hardening."""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    hash_password,
    verify_employee_password,
)
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.email import EmailService
from app.services.refresh_session import SUBJECT_EMPLOYEE, RefreshSessionService
from tests.conftest import auth_header, _uow_factory, tenant_tokens_from_response


@pytest.fixture
def bot_service_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-bot-service-token-secure"
    monkeypatch.setenv("BOT_SERVICE_TOKEN", token)
    get_settings.cache_clear()
    # Force settings reload with patched env
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", token)
    yield token
    get_settings.cache_clear()


async def test_deactivated_company_blocks_login_and_api(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    settings = get_settings()
    password = settings.auth_password

    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(admin_a.id), "password": password},
    )
    assert login.status_code == 200, login.text
    tokens = tenant_tokens_from_response(login)
    token = tokens["access_token"]
    refresh = tokens["refresh_token"]
    assert "access_token" not in login.json()
    assert "refresh_token" not in login.json()

    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.companies.update(company_a.id, is_active=False)
        await uow.commit()

    blocked_login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(admin_a.id), "password": password},
    )
    assert blocked_login.status_code == 403
    assert "deactivated" in blocked_login.json()["detail"].lower()

    me = await api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 403

    refreshed = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert refreshed.status_code == 403


async def test_shared_auth_password_disabled_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_shared_auth_password", False)
    assert verify_employee_password(password=settings.auth_password, password_hash=None) is False
    assert (
        verify_employee_password(
            password="correct-horse",
            password_hash=hash_password("correct-horse"),
        )
        is True
    )


async def test_bot_login_rejects_foreign_company(
    api_client: AsyncClient,
    company_a,
    company_b,
    employee_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_company_id", str(company_a.id))
    monkeypatch.setattr(settings, "bot_service_token", bot_service_token)

    ok = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": employee_a.telegram_user_id,
        },
    )
    assert ok.status_code == 200, ok.text

    denied = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "company_id": str(company_b.id),
            "telegram_user_id": 999999001,
        },
    )
    assert denied.status_code == 403
    assert "not authorized" in denied.json()["detail"].lower()


async def test_hr_cannot_promote_to_admin(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(hr_a),
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": 88001001,
            "full_name": "Would Be Admin",
            "role": "admin",
            "status": "invited",
        },
    )
    assert create.status_code == 403

    promote = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(hr_a),
        json={"role": "admin"},
    )
    assert promote.status_code == 403


async def test_hr_cannot_modify_admin_account(
    api_client: AsyncClient,
    hr_a: Employee,
    admin_a: Employee,
) -> None:
    response = await api_client.patch(
        f"/api/v1/employees/{admin_a.id}",
        headers=auth_header(hr_a),
        json={"status": "archived"},
    )
    assert response.status_code == 403


async def test_invite_email_does_not_log_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = f"secret-invite-token-{uuid4().hex}"
    invite_url = f"http://localhost:3000/invite#{token}"
    service = EmailService()
    with caplog.at_level(logging.INFO, logger="app.email"):
        await service.send_invite_email(
            to_email="user@example.com",
            full_name="Test User",
            invite_url=invite_url,
            company_name="Acme",
        )
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert token not in joined
    assert "body_omitted=true" in joined


async def test_invited_employee_cannot_refresh(
    api_client: AsyncClient,
    company_a,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        invited = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                telegram_user_id=77001001,
                full_name="Invited User",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.INVITED.value,
                password_hash=hash_password("Temporary1!"),
            ),
        )
        await uow.commit()

    issued = await RefreshSessionService().issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=invited.id,
        role=invited.role,
        company_id=invited.company_id,
    )
    response = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": issued.tokens.refresh_token},
    )
    assert response.status_code == 403


async def test_access_token_rejected_when_company_deactivated(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    token = create_access_token(
        subject=hr_a.id,
        role=hr_a.role,
        company_id=hr_a.company_id,
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.companies.update(company_a.id, is_active=False)
        await uow.commit()

    response = await api_client.get(
        f"/api/v1/employees?company_id={company_a.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
