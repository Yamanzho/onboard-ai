"""API tests for company-wide assignment listing and get-by-id."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.models.company import Company
from app.db.models.employee import Employee
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_list_and_get_assignment(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    headers = auth_header(hr_a)

    employee_res = await api_client.post(
        "/api/v1/employees",
        headers=headers,
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 10,
            "full_name": "Assignee",
            "role": "employee",
            "status": "invited",
        },
    )
    assert employee_res.status_code == 201, employee_res.text
    employee_id = employee_res.json()["id"]

    program_res = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={
            "company_id": str(company_a.id),
            "title": f"Prog {uuid4().hex[:8]}",
        },
    )
    assert program_res.status_code == 201, program_res.text
    program_id = program_res.json()["id"]

    step_res = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={"title": "Step 1", "step_type": "content"},
    )
    assert step_res.status_code == 201, step_res.text

    publish_res = await api_client.post(
        f"/api/v1/programs/{program_id}/publish",
        headers=headers,
    )
    assert publish_res.status_code == 200, publish_res.text

    create_res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "employee_id": employee_id,
            "program_id": program_id,
            "assigned_by_id": str(hr_a.id),
        },
    )
    assert create_res.status_code == 201, create_res.text
    assignment_id = create_res.json()["id"]

    listed = await api_client.get(
        "/api/v1/assignments",
        headers=headers,
        params={"company_id": str(company_a.id)},
    )
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()}
    assert assignment_id in ids

    got = await api_client.get(
        f"/api/v1/assignments/{assignment_id}",
        headers=headers,
    )
    assert got.status_code == 200
    assert got.json()["employee_id"] == employee_id
    assert got.json()["program_id"] == program_id
    assert got.json()["status"] == "pending"
