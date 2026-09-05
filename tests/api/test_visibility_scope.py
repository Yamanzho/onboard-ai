"""Own / department / all visibility for progress and assignments."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core import capabilities as capability_catalog
from app.core.capabilities import Capability
from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.department import Department
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header, unique_telegram_user_id

_PASSWORD = "ScopePass1!"


async def _create_department(company_id, *, name: str) -> Department:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        department = await uow.departments.create(
            Department(
                company_id=company_id,
                name=name,
                slug=f"{name.lower()}-{uuid4().hex[:8]}",
            ),
        )
        await uow.commit()
        return department


async def _create_employee(
    company_id,
    *,
    role: str,
    department_id=None,
    full_name: str = "Scoped User",
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=unique_telegram_user_id(),
                full_name=full_name,
                email=f"{uuid4().hex[:8]}@example.com",
                role=role,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password(_PASSWORD),
                department_id=department_id,
            ),
        )
        await uow.commit()
        return employee


async def _publish_program(api_client: AsyncClient, headers, company_id) -> str:
    program = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={"company_id": str(company_id), "title": f"Scope {uuid4().hex[:6]}"},
    )
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]
    step = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={"title": "Read", "step_type": "content", "content": {"body": "Hi"}},
    )
    assert step.status_code == 201, step.text
    published = await api_client.post(
        f"/api/v1/programs/{program_id}/publish",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    return program_id


async def _assign(api_client: AsyncClient, headers, employee_id, program_id) -> str:
    res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={"employee_id": str(employee_id), "program_id": program_id},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _department_caps(_employee: Employee) -> frozenset[str]:
    return frozenset(
        {
            Capability.ASSIGNMENTS_VIEW_DEPARTMENT,
            Capability.ASSIGNMENTS_MANAGE,
            Capability.COURSES_ASSIGN,
            Capability.DEADLINES_MANAGE,
            Capability.PROGRESS_VIEW_DEPARTMENT,
            Capability.ANALYTICS_VIEW,
            Capability.EMPLOYEES_VIEW,
            Capability.COURSES_VIEW,
        }
    )


@pytest.mark.asyncio
async def test_own_department_all_and_cross_tenant_visibility(
    api_client: AsyncClient,
    company_a,
    company_b,
    hr_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dept_a = await _create_department(company_a.id, name="Alpha")
    dept_b = await _create_department(company_a.id, name="Beta")
    same = await _create_employee(
        company_a.id,
        role=EmployeeRole.EMPLOYEE.value,
        department_id=dept_a.id,
        full_name="Same Dept",
    )
    other = await _create_employee(
        company_a.id,
        role=EmployeeRole.EMPLOYEE.value,
        department_id=dept_b.id,
        full_name="Other Dept",
    )
    other_tenant = await _create_employee(
        company_b.id,
        role=EmployeeRole.EMPLOYEE.value,
        full_name="Other Tenant",
    )
    dept_hr = await _create_employee(
        company_a.id,
        role=EmployeeRole.HR.value,
        department_id=dept_a.id,
        full_name="Dept HR",
    )

    admin_headers = auth_header(hr_a)
    program_id = await _publish_program(api_client, admin_headers, company_a.id)
    same_assignment = await _assign(api_client, admin_headers, same.id, program_id)
    other_assignment = await _assign(api_client, admin_headers, other.id, program_id)

    # Own: employee sees only self.
    own_list = await api_client.get(
        f"/api/v1/employees/{same.id}/assignments",
        headers=auth_header(same),
    )
    assert own_list.status_code == 200
    assert {row["id"] for row in own_list.json()} == {same_assignment}
    peer = await api_client.get(
        f"/api/v1/employees/{other.id}/assignments",
        headers=auth_header(same),
    )
    assert peer.status_code == 403
    other_progress = await api_client.get(
        f"/api/v1/assignments/{other_assignment}/progress",
        headers=auth_header(same),
    )
    assert other_progress.status_code == 403

    original = capability_catalog.capabilities_for_employee

    def _patched(employee: Employee) -> frozenset[str]:
        if employee.id == dept_hr.id:
            return _department_caps(employee)
        return original(employee)

    monkeypatch.setattr(capability_catalog, "capabilities_for_employee", _patched)

    dept_headers = auth_header(dept_hr)
    dept_list = await api_client.get(
        f"/api/v1/assignments?company_id={company_a.id}",
        headers=dept_headers,
    )
    assert dept_list.status_code == 200, dept_list.text
    ids = {row["id"] for row in dept_list.json()}
    assert same_assignment in ids
    assert other_assignment not in ids

    same_progress = await api_client.get(
        f"/api/v1/assignments/{same_assignment}/progress",
        headers=dept_headers,
    )
    assert same_progress.status_code == 200
    leak_progress = await api_client.get(
        f"/api/v1/assignments/{other_assignment}/progress",
        headers=dept_headers,
    )
    assert leak_progress.status_code == 403

    # All-scope HR sees the whole company, still not the other tenant.
    all_list = await api_client.get(
        f"/api/v1/assignments?company_id={company_a.id}",
        headers=admin_headers,
    )
    assert all_list.status_code == 200
    all_ids = {row["id"] for row in all_list.json()}
    assert same_assignment in all_ids
    assert other_assignment in all_ids

    foreign = await api_client.get(
        f"/api/v1/employees/{other_tenant.id}/assignments",
        headers=admin_headers,
    )
    assert foreign.status_code in {403, 404}
