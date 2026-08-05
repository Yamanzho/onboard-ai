"""API tests for listing program steps."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.models.company import Company
from app.db.models.employee import Employee
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_list_program_steps(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    headers = auth_header(hr_a)

    create_program = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={
            "company_id": str(company_a.id),
            "title": f"Program {uuid4().hex[:8]}",
            "description": "Test",
        },
    )
    assert create_program.status_code == 201, create_program.text
    program_id = create_program.json()["id"]

    empty = await api_client.get(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
    )
    assert empty.status_code == 200
    assert empty.json() == []

    created = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={
            "title": "Welcome",
            "step_type": "content",
            "content": {"body": "Hello"},
            "is_required": True,
            "estimated_minutes": 10,
        },
    )
    assert created.status_code == 201, created.text

    listed = await api_client.get(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
    )
    assert listed.status_code == 200
    steps = listed.json()
    assert len(steps) == 1
    assert steps[0]["title"] == "Welcome"
    assert steps[0]["position"] == 0
    assert steps[0]["step_type"] == "content"


@pytest.mark.asyncio
async def test_reorder_and_delete_steps(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    """Two-phase position updates must not violate position >= 0 CHECK."""
    headers = auth_header(hr_a)

    program = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={
            "company_id": str(company_a.id),
            "title": f"Reorder {uuid4().hex[:8]}",
        },
    )
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]

    step_ids: list[str] = []
    for title in ("A", "B", "C"):
        created = await api_client.post(
            f"/api/v1/programs/{program_id}/steps",
            headers=headers,
            json={"title": title, "step_type": "content", "content": {"body": title}},
        )
        assert created.status_code == 201, created.text
        step_ids.append(created.json()["id"])

    new_order = [step_ids[2], step_ids[0], step_ids[1]]
    reordered = await api_client.post(
        f"/api/v1/programs/{program_id}/steps/reorder",
        headers=headers,
        json={"step_ids": new_order},
    )
    assert reordered.status_code == 200, reordered.text
    assert [s["id"] for s in reordered.json()] == new_order
    assert [s["position"] for s in reordered.json()] == [0, 1, 2]

    deleted = await api_client.delete(
        f"/api/v1/steps/{step_ids[1]}",
        headers=headers,
    )
    assert deleted.status_code == 204, deleted.text

    listed = await api_client.get(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
    )
    assert listed.status_code == 200
    remaining = listed.json()
    assert len(remaining) == 2
    assert [s["position"] for s in remaining] == [0, 1]
    assert {s["id"] for s in remaining} == {step_ids[0], step_ids[2]}
