"""Super Admin employee restore / unblock."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.enums import (
    AssignmentStatus,
    EmployeeRole,
    EmployeeStatus,
    PlatformAuditAction,
    PlatformRole,
)
from app.db.models.assignment import Assignment
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.onboarding_program import OnboardingProgram
from app.db.models.super_admin import SuperAdmin
from tests.conftest import _uow_factory, auth_header


def _sa_header(admin: SuperAdmin) -> dict[str, str]:
    token = create_access_token(
        subject=admin.id,
        role=PlatformRole.SUPER_ADMIN.value,
        company_id=None,
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_super_admin() -> SuperAdmin:
    suffix = uuid4().hex[:8]
    async with _uow_factory() as uow:
        await uow.enter_platform()
        admin = await uow.super_admins.create(
            SuperAdmin(
                email=f"sa-restore-{suffix}@test.local",
                full_name="Restore Super Admin",
                password_hash=hash_password("super-secret"),
                is_active=True,
            ),
        )
        await uow.commit()
        return admin


async def _create_employee(
    company_id,
    *,
    role: str = EmployeeRole.EMPLOYEE.value,
    status: str = EmployeeStatus.ACTIVE.value,
    password: str | None = "RestorePass1!",
    telegram_user_id: int | None = None,
    telegram_chat_id: int | None = None,
    telegram_username: str | None = None,
    email: str | None = None,
    full_name: str = "Restore Target",
) -> Employee:
    suffix = uuid4().int % 1_000_000_000
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=telegram_user_id or (suffix + 1),
                telegram_chat_id=telegram_chat_id,
                telegram_username=telegram_username,
                full_name=full_name,
                email=email or f"restore-{uuid4().hex[:8]}@example.com",
                role=role,
                status=status,
                password_hash=hash_password(password) if password else None,
            ),
        )
        await uow.commit()
        return employee


async def _reload(employee_id) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        row = await uow.employees.get_by_id(employee_id)
        assert row is not None
        return row


@pytest.fixture
async def super_admin() -> SuperAdmin:
    return await _create_super_admin()


@pytest.fixture
def bot_service_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-bot-restore-service-token-32c"
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


async def _bot_login(
    api_client: AsyncClient,
    *,
    company_id,
    telegram_user_id: int,
    bot_token: str,
):
    return await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers={"X-Bot-Service-Token": bot_token},
        json={"company_id": str(company_id), "telegram_user_id": telegram_user_id},
    )


@pytest.mark.asyncio
async def test_active_archive_restore_returns_active(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
) -> None:
    employee = await _create_employee(company_a.id, role=EmployeeRole.HR.value)
    headers = _sa_header(super_admin)

    blocked = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/block",
        headers=headers,
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == EmployeeStatus.ARCHIVED.value

    restored = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/restore",
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == EmployeeStatus.ACTIVE.value
    assert restored.json()["role"] == EmployeeRole.HR.value
    assert restored.json()["company_id"] == str(company_a.id)

    refreshed = await _reload(employee.id)
    assert refreshed.status == EmployeeStatus.ACTIVE.value
    assert refreshed.password_hash == employee.password_hash
    assert refreshed.telegram_user_id == employee.telegram_user_id


@pytest.mark.asyncio
async def test_invited_archive_restore_stays_invited(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
) -> None:
    employee = await _create_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
        password=None,
        telegram_chat_id=None,
        telegram_username=None,
    )
    headers = _sa_header(super_admin)

    blocked = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/block",
        headers=headers,
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == EmployeeStatus.ARCHIVED.value

    restored = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/restore",
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == EmployeeStatus.INVITED.value

    refreshed = await _reload(employee.id)
    assert refreshed.status == EmployeeStatus.INVITED.value
    assert refreshed.password_hash is None


@pytest.mark.asyncio
async def test_invited_restore_still_requires_invite_accept(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    headers = _sa_header(super_admin)

    created = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "Never Activated",
            "email": f"never-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]
    token = created.json()["invite_url"].split("#", 1)[1]

    blocked = await api_client.post(
        f"/api/v1/super-admin/users/{employee_id}/block",
        headers=headers,
    )
    assert blocked.json()["status"] == EmployeeStatus.ARCHIVED.value

    restored = await api_client.post(
        f"/api/v1/super-admin/users/{employee_id}/restore",
        headers=headers,
    )
    assert restored.json()["status"] == EmployeeStatus.INVITED.value

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": "AfterRestore1!"},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == EmployeeStatus.ACTIVE.value
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_restore_active_or_invited_is_rejected(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
) -> None:
    headers = _sa_header(super_admin)
    active = await _create_employee(company_a.id)
    invited = await _create_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
        password=None,
    )

    active_res = await api_client.post(
        f"/api/v1/super-admin/users/{active.id}/restore",
        headers=headers,
    )
    assert active_res.status_code == 400, active_res.text
    assert "archived" in active_res.json()["detail"].lower()
    assert (await _reload(active.id)).status == EmployeeStatus.ACTIVE.value

    invited_res = await api_client.post(
        f"/api/v1/super-admin/users/{invited.id}/restore",
        headers=headers,
    )
    assert invited_res.status_code == 400, invited_res.text
    assert (await _reload(invited.id)).status == EmployeeStatus.INVITED.value


@pytest.mark.asyncio
@pytest.mark.security
async def test_restore_unauthorized_denied(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    admin_a: Employee,
) -> None:
    employee = await _create_employee(company_a.id)
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employees.update(employee.id, status=EmployeeStatus.ARCHIVED.value)
        await uow.commit()

    path = f"/api/v1/super-admin/users/{employee.id}/restore"
    anon = await api_client.post(path)
    assert anon.status_code == 401

    hr = await api_client.post(path, headers=auth_header(hr_a))
    assert hr.status_code == 401

    admin = await api_client.post(path, headers=auth_header(admin_a))
    assert admin.status_code == 401

    assert (await _reload(employee.id)).status == EmployeeStatus.ARCHIVED.value


@pytest.mark.asyncio
async def test_restore_unknown_employee_404(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
) -> None:
    missing = uuid4()
    res = await api_client.post(
        f"/api/v1/super-admin/users/{missing}/restore",
        headers=_sa_header(super_admin),
    )
    assert res.status_code == 404
    assert str(missing) in res.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.security
async def test_restore_is_platform_scoped_across_companies(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_b: Company,
) -> None:
    employee = await _create_employee(
        company_b.id,
        role=EmployeeRole.ADMIN.value,
    )
    headers = _sa_header(super_admin)
    blocked = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/block",
        headers=headers,
    )
    assert blocked.status_code == 200
    restored = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/restore",
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["company_id"] == str(company_b.id)
    assert restored.json()["status"] == EmployeeStatus.ACTIVE.value


@pytest.mark.asyncio
@pytest.mark.telegram
async def test_telegram_login_archive_restore_roundtrip(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_bot_company(monkeypatch, company_a.id)
    tg_id = 9_300_000_101
    chat_id = 9_300_000_201
    employee = await _create_employee(
        company_a.id,
        telegram_user_id=tg_id,
        telegram_chat_id=chat_id,
        telegram_username="restore_bot",
    )
    headers = _sa_header(super_admin)

    before = await _bot_login(
        api_client,
        company_id=company_a.id,
        telegram_user_id=tg_id,
        bot_token=bot_service_token,
    )
    assert before.status_code == 200, before.text

    blocked = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/block",
        headers=headers,
    )
    assert blocked.json()["status"] == EmployeeStatus.ARCHIVED.value

    archived_login = await _bot_login(
        api_client,
        company_id=company_a.id,
        telegram_user_id=tg_id,
        bot_token=bot_service_token,
    )
    assert archived_login.status_code == 403
    assert "archived" in archived_login.json()["detail"].lower()

    restored = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/restore",
        headers=headers,
    )
    assert restored.json()["status"] == EmployeeStatus.ACTIVE.value
    assert restored.json()["telegram_user_id"] == tg_id
    assert restored.json()["telegram_username"] == "restore_bot"

    after = await _bot_login(
        api_client,
        company_id=company_a.id,
        telegram_user_id=tg_id,
        bot_token=bot_service_token,
    )
    assert after.status_code == 200, after.text

    refreshed = await _reload(employee.id)
    assert refreshed.telegram_user_id == tg_id
    assert refreshed.telegram_chat_id == chat_id
    assert refreshed.telegram_username == "restore_bot"
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.telegram
async def test_telegram_bound_without_password_restores_active(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_demo_bot")
    _bind_bot_company(monkeypatch, company_a.id)
    headers = _sa_header(super_admin)
    tg_id = 9_300_000_301
    chat_id = 9_300_000_401

    created = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "TG Only Restore",
            "email": f"tg-restore-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]
    token = created.json()["invite_url"].split("#", 1)[1]

    accept = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token,
            "telegram_user_id": tg_id,
            "telegram_username": "tg_only_restore",
            "telegram_chat_id": chat_id,
            "company_id": str(company_a.id),
        },
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["employee"]["status"] == EmployeeStatus.ACTIVE.value

    blocked = await api_client.post(
        f"/api/v1/super-admin/users/{employee_id}/block",
        headers=headers,
    )
    assert blocked.json()["status"] == EmployeeStatus.ARCHIVED.value

    restored = await api_client.post(
        f"/api/v1/super-admin/users/{employee_id}/restore",
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == EmployeeStatus.ACTIVE.value

    refreshed = await _reload(employee_id)
    assert refreshed.password_hash is None
    assert refreshed.telegram_user_id == tg_id
    assert refreshed.telegram_chat_id == chat_id
    assert refreshed.telegram_username == "tg_only_restore"

    login = await _bot_login(
        api_client,
        company_id=company_a.id,
        telegram_user_id=tg_id,
        bot_token=bot_service_token,
    )
    assert login.status_code == 200, login.text
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_restore_preserves_assignments_identity_and_audit(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
) -> None:
    employee = await _create_employee(
        company_a.id,
        telegram_user_id=9_300_000_501,
        telegram_chat_id=9_300_000_601,
        telegram_username="keep_identity",
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        program = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_a.id,
                title=f"Restore Program {uuid4().hex[:8]}",
                is_active=True,
            ),
        )
        assignment = await uow.assignments.create(
            Assignment(
                company_id=company_a.id,
                employee_id=employee.id,
                program_id=program.id,
                status=AssignmentStatus.IN_PROGRESS.value,
                assigned_at=datetime.now(UTC),
            ),
        )
        await uow.commit()
        assignment_id = assignment.id

    headers = _sa_header(super_admin)
    blocked = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/block",
        headers=headers,
    )
    assert blocked.status_code == 200
    restored = await api_client.post(
        f"/api/v1/super-admin/users/{employee.id}/restore",
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == EmployeeStatus.ACTIVE.value

    async with _uow_factory() as uow:
        await uow.enter_platform()
        refreshed_assignment = await uow.assignments.get_by_id(assignment_id)
        logs = await uow.platform_audit_logs.list_recent(offset=0, limit=50)
        restored_emp = await uow.employees.get_by_id(employee.id)

    assert refreshed_assignment is not None
    assert refreshed_assignment.status == AssignmentStatus.IN_PROGRESS.value
    assert refreshed_assignment.employee_id == employee.id
    assert restored_emp is not None
    assert restored_emp.telegram_user_id == 9_300_000_501
    assert restored_emp.telegram_chat_id == 9_300_000_601
    assert restored_emp.telegram_username == "keep_identity"
    assert restored_emp.role == EmployeeRole.EMPLOYEE.value
    assert restored_emp.company_id == company_a.id
    assert any(
        log.action == PlatformAuditAction.USER_RESTORED.value
        and log.resource_id == employee.id
        for log in logs
    )


def test_restore_service_only_updates_status() -> None:
    """Conversations/assignments/Telegram are not written by restore."""
    from pathlib import Path

    src = Path("app/services/platform.py").read_text(encoding="utf-8")
    start = src.index("async def restore_company_user")
    end = src.index("def _can_restore_to_active", start)
    body = src[start:end]
    assert "employees.update(employee_id, status=next_status)" in body
    assert "telegram_user_id=" not in body
    assert "telegram_chat_id=" not in body
    assert "telegram_username=" not in body
    assert "assignments" not in body
    assert "ai_conversations" not in body
    assert "password_hash=" not in body
    assert "revoke_all_for_subject" not in body
