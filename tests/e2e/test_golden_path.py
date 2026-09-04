"""Production-pilot golden path as an automated API flow.

Telegram Bot API is not called. Binding uses the existing bot→API boundary
(``POST /api/v1/auth/bot/invite/accept`` + service token), matching production.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus, ProgressStatus
from app.db.models.super_admin import SuperAdmin
from app.db.uow import UnitOfWork
from tests.conftest import (
    sa_tokens_from_response,
    tenant_tokens_from_response,
    unique_telegram_user_id,
)

_PASSWORD = "PilotPass1!"
_BOT_SERVICE_TOKEN = "ci-golden-path-bot-service-token-32c"


async def _create_super_admin() -> tuple[SuperAdmin, str]:
    suffix = uuid4().hex[:8]
    email = f"sa-pilot-{suffix}@test.local"
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        admin = await uow.super_admins.create(
            SuperAdmin(
                email=email,
                full_name="Pilot Super Admin",
                password_hash=hash_password(_PASSWORD),
                is_active=True,
            ),
        )
        await uow.commit()
        return admin, _PASSWORD


def _invite_token(invite_url: str | None) -> str:
    assert invite_url, "expected invite_url when SMTP is unset"
    assert "/invite#" in invite_url
    token = invite_url.split("#", 1)[1]
    assert token
    return token


def _bearer(access: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access}"}


def _bind_bot_company(monkeypatch: pytest.MonkeyPatch, company_id) -> None:
    monkeypatch.setenv("BOT_SERVICE_TOKEN", _BOT_SERVICE_TOKEN)
    monkeypatch.setenv("BOT_COMPANY_ID", str(company_id))
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_pilot_bot")
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", _BOT_SERVICE_TOKEN)
    monkeypatch.setattr(settings, "bot_company_id", str(company_id))
    monkeypatch.setattr(settings, "telegram_bot_username", "onboardai_pilot_bot")
    settings.bot_login_rate_limit = 0
    settings.login_rate_limit = 0
    settings.invite_preview_rate_limit = 0
    settings.invite_accept_rate_limit = 0


@pytest.mark.asyncio
async def test_production_pilot_golden_path(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()

    sa, password = await _create_super_admin()
    login_sa = await api_client.post(
        "/api/v1/super-admin/auth/login",
        json={"email": sa.email, "password": password},
    )
    assert login_sa.status_code == 200, login_sa.text
    sa_headers = _bearer(sa_tokens_from_response(login_sa)["access_token"])

    slug = f"pilot-{uuid4().hex[:8]}"
    admin_email = f"admin@{slug}.test"
    create_company = await api_client.post(
        "/api/v1/super-admin/companies",
        headers=sa_headers,
        json={
            "name": "Pilot Tenant",
            "slug": slug,
            "timezone": "UTC",
            "admin_full_name": "Pilot Admin",
            "admin_email": admin_email,
            "admin_telegram_user_id": uuid4().int % 1_000_000_000 + 70,
        },
    )
    assert create_company.status_code == 201, create_company.text
    company = create_company.json()
    company_id = company["id"]
    assert company["subscription"]["status"] == "trial"
    admin_token = _invite_token(company.get("invite_url"))

    accept_admin = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": admin_token, "password": _PASSWORD},
    )
    assert accept_admin.status_code == 200, accept_admin.text
    assert accept_admin.json()["status"] == EmployeeStatus.ACTIVE.value
    assert accept_admin.json()["role"] == EmployeeRole.ADMIN.value

    replay_admin = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": admin_token, "password": "OtherPass1!"},
    )
    assert replay_admin.status_code in {400, 404}, replay_admin.text

    login_admin = await api_client.post(
        "/api/v1/auth/login",
        data={"username": admin_email, "password": _PASSWORD},
    )
    assert login_admin.status_code == 200, login_admin.text
    admin_headers = _bearer(tenant_tokens_from_response(login_admin)["access_token"])

    hr_email = f"hr@{slug}.test"
    create_hr = await api_client.post(
        "/api/v1/employees",
        headers=admin_headers,
        json={
            "company_id": company_id,
            "full_name": "Pilot HR",
            "email": hr_email,
            "role": "hr",
            "status": "invited",
        },
    )
    assert create_hr.status_code == 201, create_hr.text
    hr_token = _invite_token(create_hr.json().get("invite_url"))

    accept_hr = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": hr_token, "password": _PASSWORD},
    )
    assert accept_hr.status_code == 200, accept_hr.text
    assert accept_hr.json()["role"] == EmployeeRole.HR.value

    login_hr = await api_client.post(
        "/api/v1/auth/login",
        data={"username": hr_email, "password": _PASSWORD},
    )
    assert login_hr.status_code == 200, login_hr.text
    hr_headers = _bearer(tenant_tokens_from_response(login_hr)["access_token"])

    emp_email = f"employee@{slug}.test"
    create_emp = await api_client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "company_id": company_id,
            "full_name": "Pilot Employee",
            "email": emp_email,
            "role": "employee",
            "status": "invited",
        },
    )
    assert create_emp.status_code == 201, create_emp.text
    employee_id = create_emp.json()["id"]
    emp_invite_url = create_emp.json().get("invite_url")
    emp_token = _invite_token(emp_invite_url)

    _bind_bot_company(monkeypatch, company_id)
    tg_id = unique_telegram_user_id()
    bind = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": _BOT_SERVICE_TOKEN},
        json={
            "token": emp_token,
            "telegram_user_id": tg_id,
            "telegram_username": "pilot_employee",
            "company_id": company_id,
        },
    )
    assert bind.status_code == 200, bind.text
    assert bind.json()["employee"]["status"] == EmployeeStatus.ACTIVE.value
    assert bind.json()["employee"]["telegram_user_id"] == tg_id
    employee_headers = _bearer(bind.json()["access_token"])

    replay_tg = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": _BOT_SERVICE_TOKEN},
        json={
            "token": emp_token,
            "telegram_user_id": tg_id + 1,
            "company_id": company_id,
        },
    )
    assert replay_tg.status_code in {400, 403, 404}, replay_tg.text

    create_program = await api_client.post(
        "/api/v1/programs",
        headers=hr_headers,
        json={"company_id": company_id, "title": "Pilot onboarding"},
    )
    assert create_program.status_code == 201, create_program.text
    program_id = create_program.json()["id"]

    create_step = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=hr_headers,
        json={
            "title": "Welcome",
            "step_type": "content",
            "content": {"body": "Hello from the pilot"},
        },
    )
    assert create_step.status_code == 201, create_step.text

    publish = await api_client.post(
        f"/api/v1/programs/{program_id}/publish",
        headers=hr_headers,
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["is_active"] is True

    assign = await api_client.post(
        "/api/v1/assignments",
        headers=hr_headers,
        json={"employee_id": employee_id, "program_id": program_id},
    )
    assert assign.status_code == 201, assign.text
    assignment_id = assign.json()["id"]

    progress_list = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=employee_headers,
    )
    assert progress_list.status_code == 200, progress_list.text
    items = progress_list.json()["items"]
    assert len(items) == 1
    progress_id = items[0]["id"]

    complete = await api_client.post(
        f"/api/v1/progress/{progress_id}/complete",
        headers=employee_headers,
        json={"payload": {"ack": True}},
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == ProgressStatus.COMPLETED.value

    hr_view = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=hr_headers,
    )
    assert hr_view.status_code == 200, hr_view.text
    body = hr_view.json()
    assert body["percentage"] == 100
    assert body["items"][0]["status"] == ProgressStatus.COMPLETED.value
