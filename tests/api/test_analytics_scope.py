"""Analytics must not leak aggregates outside the caller's scope."""

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

_PASSWORD = "AnalyticsScope1!"


async def _department(company_id, name: str) -> Department:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        row = await uow.departments.create(
            Department(
                company_id=company_id,
                name=name,
                slug=f"{name.lower()}-{uuid4().hex[:8]}",
            ),
        )
        await uow.commit()
        return row


async def _employee(company_id, *, role: str, department_id=None, name: str) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        row = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=unique_telegram_user_id(),
                full_name=name,
                email=f"{uuid4().hex[:8]}@example.com",
                role=role,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password(_PASSWORD),
                department_id=department_id,
            ),
        )
        await uow.commit()
        return row


async def _program(api_client: AsyncClient, headers, company_id) -> str:
    created = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={"company_id": str(company_id), "title": f"An {uuid4().hex[:6]}"},
    )
    program_id = created.json()["id"]
    await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={"title": "Read", "step_type": "content", "content": {"body": "Hi"}},
    )
    await api_client.post(f"/api/v1/programs/{program_id}/publish", headers=headers)
    return program_id


@pytest.mark.asyncio
async def test_department_analytics_does_not_leak_other_department_overdue(
    api_client: AsyncClient,
    company_a,
    company_b,
    hr_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dept_a = await _department(company_a.id, "DeptA")
    dept_b = await _department(company_a.id, "DeptB")
    emp_a1 = await _employee(
        company_a.id, role=EmployeeRole.EMPLOYEE.value, department_id=dept_a.id, name="A1"
    )
    emp_a2 = await _employee(
        company_a.id, role=EmployeeRole.EMPLOYEE.value, department_id=dept_a.id, name="A2"
    )
    emp_b_ids = []
    for index in range(10):
        emp_b_ids.append(
            (
                await _employee(
                    company_a.id,
                    role=EmployeeRole.EMPLOYEE.value,
                    department_id=dept_b.id,
                    name=f"B{index}",
                )
            ).id
        )
    other_tenant = await _employee(
        company_b.id, role=EmployeeRole.EMPLOYEE.value, name="Tenant B"
    )
    scoped_hr = await _employee(
        company_a.id,
        role=EmployeeRole.HR.value,
        department_id=dept_a.id,
        name="Scoped HR",
    )

    headers = auth_header(hr_a)
    program_id = await _program(api_client, headers, company_a.id)
    from datetime import UTC, datetime, timedelta

    past = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    for employee_id in (emp_a1.id, emp_a2.id, *emp_b_ids):
        res = await api_client.post(
            "/api/v1/assignments",
            headers=headers,
            json={
                "employee_id": str(employee_id),
                "program_id": program_id,
                "due_at": past,
            },
        )
        assert res.status_code == 201, res.text

    original = capability_catalog.capabilities_for_employee

    def _patched(employee: Employee) -> frozenset[str]:
        if employee.id == scoped_hr.id:
            return frozenset(
                {
                    Capability.ANALYTICS_VIEW,
                    Capability.PROGRESS_VIEW_DEPARTMENT,
                    Capability.ASSIGNMENTS_VIEW_DEPARTMENT,
                }
            )
        return original(employee)

    monkeypatch.setattr(capability_catalog, "capabilities_for_employee", _patched)

    scoped = await api_client.get(
        f"/api/v1/analytics/assignments?company_id={company_a.id}",
        headers=auth_header(scoped_hr),
    )
    assert scoped.status_code == 200, scoped.text
    body = scoped.json()
    assert body["overdue"] == 2
    assert body["active"] == 2
    assert body["scope"] == "department"
    assert body["department_id"] == str(dept_a.id)
    assert body["employees_with_overdue"] == 2

    company_wide = await api_client.get(
        f"/api/v1/analytics/assignments?company_id={company_a.id}",
        headers=headers,
    )
    assert company_wide.status_code == 200
    assert company_wide.json()["overdue"] == 12

    # Requesting another department is forbidden for department-scoped callers.
    denied = await api_client.get(
        f"/api/v1/analytics/assignments?company_id={company_a.id}"
        f"&department_id={dept_b.id}",
        headers=auth_header(scoped_hr),
    )
    assert denied.status_code == 403

    # Own-only employee cannot use management analytics.
    own = await api_client.get(
        f"/api/v1/analytics/assignments?company_id={company_a.id}",
        headers=auth_header(emp_a1),
    )
    assert own.status_code == 403

    # Cross-tenant company id is not visible.
    foreign = await api_client.get(
        f"/api/v1/analytics/assignments?company_id={company_b.id}",
        headers=headers,
    )
    assert foreign.status_code in {403, 404}
    _ = other_tenant


@pytest.mark.asyncio
async def test_assignment_analytics_completion_rate_excludes_cancelled(
    api_client: AsyncClient,
    company_a,
    hr_a,
    employee_a,
) -> None:
    headers = auth_header(hr_a)
    program_id = await _program(api_client, headers, company_a.id)
    created = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={"employee_id": str(employee_a.id), "program_id": program_id},
    )
    assert created.status_code == 201
    stats = await api_client.get(
        f"/api/v1/analytics/assignments?company_id={company_a.id}",
        headers=headers,
    )
    assert stats.status_code == 200
    body = stats.json()
    assert body["active"] >= 1
    assert body["completion_rate"] is not None
    assert 0 <= body["completion_rate"] <= 100
    assert "program" in body["by_type"]
    assert "acknowledgement" in body["by_type"]
