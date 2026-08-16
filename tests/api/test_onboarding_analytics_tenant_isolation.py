"""Onboarding analytics stay inside the caller's tenant."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from tests.conftest import auth_header


async def _activate(employee_id) -> None:
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.employees.update(employee_id, status=EmployeeStatus.ACTIVE.value)
        await uow.commit()


@pytest.mark.asyncio
async def test_onboarding_analytics_tenant_isolation(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    hr_b: Employee,
    employee_a: Employee,
) -> None:
    headers = auth_header(hr_a)
    emp = await api_client.post(
        "/api/v1/employees",
        headers=headers,
        json={
            "company_id": str(company_a.id),
            "full_name": "Analytics Emp",
            "email": f"an-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert emp.status_code == 201, emp.text
    employee_id = emp.json()["id"]
    await _activate(employee_id)

    program = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={"company_id": str(company_a.id), "title": f"An {uuid4().hex[:6]}"},
    )
    program_id = program.json()["id"]
    step = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={"title": "Read", "step_type": "content", "content": {"body": "Hi"}},
    )
    assert step.status_code == 201
    assert (
        await api_client.post(f"/api/v1/programs/{program_id}/publish", headers=headers)
    ).status_code == 200
    assign = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={"employee_id": employee_id, "program_id": program_id},
    )
    assert assign.status_code == 201

    stats = await api_client.get(
        f"/api/v1/analytics/onboarding?company_id={company_a.id}",
        headers=headers,
    )
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["total_employees"] >= 1
    assert body["active_onboarding"] >= 1
    assert body["employees_not_started"] >= 1
    assert any(row["program_id"] == program_id for row in body["by_program"])

    emp_denied = await api_client.get(
        f"/api/v1/analytics/onboarding?company_id={company_a.id}",
        headers=auth_header(employee_a),
    )
    assert emp_denied.status_code == 403

    cross = await api_client.get(
        f"/api/v1/analytics/onboarding?company_id={company_a.id}",
        headers=auth_header(hr_b),
    )
    assert cross.status_code == 404

    other = await api_client.get(
        f"/api/v1/analytics/onboarding?company_id={company_b.id}",
        headers=auth_header(hr_b),
    )
    assert other.status_code == 200
    assert program_id not in {row["program_id"] for row in other.json()["by_program"]}
