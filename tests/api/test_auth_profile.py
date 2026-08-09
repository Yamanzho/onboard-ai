"""Sprint 1.3: GET/PATCH /auth/me profile safety and field controls."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from tests.conftest import auth_header, _uow_factory

_PASSWORD = "ProfilePass1!"
_SECRET_FIELDS = {
    "password_hash",
    "password",
    "refresh_token",
    "access_token",
    "token",
    "invite_token",
    "session_token",
}


async def _active_employee(company_id, *, role: str = EmployeeRole.EMPLOYEE.value) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 6000,
                full_name="Profile User",
                email=f"profile-{uuid4().hex[:8]}@example.com",
                role=role,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password(_PASSWORD),
            ),
        )
        await uow.commit()
        return employee


async def test_get_auth_me_returns_safe_fields(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _active_employee(company_a.id, role=EmployeeRole.ADMIN.value)
    res = await api_client.get("/api/v1/auth/me", headers=auth_header(employee))
    assert res.status_code == 200, res.text
    body = res.json()
    for key in (
        "id",
        "company_id",
        "full_name",
        "email",
        "role",
        "status",
        "telegram_user_id",
        "telegram_connected",
        "created_at",
        "updated_at",
    ):
        assert key in body
    assert body["id"] == str(employee.id)
    assert body["company_id"] == str(company_a.id)
    assert body["company_name"] == company_a.name
    for secret in _SECRET_FIELDS:
        assert secret not in body


async def test_patch_auth_me_updates_allowed_fields(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _active_employee(company_a.id, role=EmployeeRole.HR.value)
    res = await api_client.patch(
        "/api/v1/auth/me",
        headers=auth_header(employee),
        json={"full_name": "Updated Name", "email": "updated@example.com"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["full_name"] == "Updated Name"
    assert body["email"] == "updated@example.com"
    assert body["role"] == EmployeeRole.HR.value
    assert body["company_id"] == str(company_a.id)
    for secret in _SECRET_FIELDS:
        assert secret not in body


@pytest.mark.parametrize(
    "payload",
    [
        {"role": "admin"},
        {"status": "archived"},
        {"company_id": "00000000-0000-0000-0000-000000000099"},
        {"telegram_user_id": 12345},
        {"id": "00000000-0000-0000-0000-000000000099"},
        {"password_hash": "x"},
    ],
)
async def test_patch_auth_me_rejects_forbidden_fields(
    api_client: AsyncClient,
    company_a,
    payload: dict,
) -> None:
    employee = await _active_employee(company_a.id)
    res = await api_client.patch(
        "/api/v1/auth/me",
        headers=auth_header(employee),
        json=payload,
    )
    assert res.status_code == 422, res.text

    async with _uow_factory() as uow:
        await uow.enter_platform()
        refreshed = await uow.employees.get_by_id(employee.id)
        assert refreshed is not None
        assert refreshed.role == employee.role
        assert refreshed.status == employee.status
        assert refreshed.company_id == employee.company_id


async def test_employee_cannot_patch_other_employee_via_employees_api(
    api_client: AsyncClient,
    company_a,
) -> None:
    actor = await _active_employee(company_a.id)
    target = await _active_employee(company_a.id)
    res = await api_client.patch(
        f"/api/v1/employees/{target.id}",
        headers=auth_header(actor),
        json={"full_name": "Hacked"},
    )
    assert res.status_code == 403, res.text
