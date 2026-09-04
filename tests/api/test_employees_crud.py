"""Sprint 1.3: employee list/get/edit RBAC and safe response fields."""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient

from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header, unique_email

_PASSWORD = "EmpCrudPass1!"
_SECRET_FIELDS = {"password_hash", "password", "refresh_token", "token"}


async def _create(
    company_id,
    *,
    role: str = EmployeeRole.EMPLOYEE.value,
    status: str = EmployeeStatus.ACTIVE.value,
    email: str | None = None,
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 5000,
                full_name="CRUD User",
                email=email or f"crud-{uuid4().hex[:8]}@example.com",
                role=role,
                status=status,
                password_hash=hash_password(_PASSWORD)
                if status == EmployeeStatus.ACTIVE.value
                else None,
            ),
        )
        await uow.commit()
        return employee


async def test_admin_list_and_get_never_expose_password(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    target = await _create(company_a.id)
    listed = await api_client.get(
        f"/api/v1/employees?company_id={company_a.id}",
        headers=auth_header(admin_a),
    )
    assert listed.status_code == 200, listed.text
    for row in listed.json():
        for secret in _SECRET_FIELDS:
            assert secret not in row

    detail = await api_client.get(
        f"/api/v1/employees/{target.id}",
        headers=auth_header(admin_a),
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == str(target.id)
    for secret in _SECRET_FIELDS:
        assert secret not in body


async def test_admin_and_hr_can_edit_allowed_fields(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    hr_a: Employee,
) -> None:
    target = await _create(company_a.id)
    admin_patch = await api_client.patch(
        f"/api/v1/employees/{target.id}",
        headers=auth_header(admin_a),
        json={"full_name": "Admin Edited", "email": unique_email("admin-edited")},
    )
    assert admin_patch.status_code == 200, admin_patch.text
    assert admin_patch.json()["full_name"] == "Admin Edited"

    hr_patch = await api_client.patch(
        f"/api/v1/employees/{target.id}",
        headers=auth_header(hr_a),
        json={"full_name": "HR Edited"},
    )
    assert hr_patch.status_code == 200, hr_patch.text
    assert hr_patch.json()["full_name"] == "HR Edited"


async def test_company_id_mutation_rejected_on_employee_patch(
    api_client: AsyncClient,
    company_a,
    company_b,
    admin_a: Employee,
) -> None:
    target = await _create(company_a.id)
    res = await api_client.patch(
        f"/api/v1/employees/{target.id}",
        headers=auth_header(admin_a),
        json={"company_id": str(company_b.id)},
    )
    # Extra fields ignored by EmployeeUpdate (no company_id) → empty patch → 422,
    # or ValidationError if passed through somehow.
    assert res.status_code in {400, 422}, res.text

    async with _uow_factory() as uow:
        await uow.enter_platform()
        refreshed = await uow.employees.get_by_id(target.id)
        assert refreshed is not None
        assert refreshed.company_id == company_a.id


async def test_hr_role_escalation_denied(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    target = await _create(company_a.id)
    res = await api_client.patch(
        f"/api/v1/employees/{target.id}",
        headers=auth_header(hr_a),
        json={"role": "admin"},
    )
    assert res.status_code == 403, res.text


async def test_cross_tenant_employee_edit_denied(
    api_client: AsyncClient,
    company_b,
    admin_a: Employee,
) -> None:
    foreign = await _create(company_b.id)
    res = await api_client.patch(
        f"/api/v1/employees/{foreign.id}",
        headers=auth_header(admin_a),
        json={"full_name": "Cross Tenant"},
    )
    assert res.status_code == 404, res.text
