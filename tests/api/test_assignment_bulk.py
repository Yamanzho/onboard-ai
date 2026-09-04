"""Phase 9C: assignment priority, overdue, bulk targeting, deadlines, isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import AssignmentStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header


async def _publish_program(client: AsyncClient, actor: Employee, company_id) -> str:
    headers = auth_header(actor)
    program = await client.post(
        "/api/v1/programs",
        headers=headers,
        json={"company_id": str(company_id), "title": f"Prog {uuid4().hex[:8]}"},
    )
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]
    step = await client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={"title": "Step 1", "step_type": "content"},
    )
    assert step.status_code == 201, step.text
    published = await client.post(f"/api/v1/programs/{program_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    return program_id


async def _create_employee_api(
    client: AsyncClient,
    actor: Employee,
    company_id,
    *,
    name: str | None = None,
) -> dict:
    res = await client.post(
        "/api/v1/employees",
        headers=auth_header(actor),
        json={
            "company_id": str(company_id),
            "full_name": name or f"Emp {uuid4().hex[:6]}",
            "email": f"emp-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _create_department(
    client: AsyncClient,
    actor: Employee,
    company_id,
    *,
    slug: str,
) -> dict:
    res = await client.post(
        "/api/v1/departments",
        headers=auth_header(actor),
        json={"company_id": str(company_id), "name": slug.upper(), "slug": slug},
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_legacy_create_defaults_priority_normal(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    employee = await _create_employee_api(api_client, hr_a, company_a.id)
    res = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={"employee_id": employee["id"], "program_id": program_id},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert "id" in body
    assert body["priority"] == "normal"
    assert body["overdue"] is False
    assert body["source_batch_id"] is None
    assert body["employee_id"] == employee["id"]


@pytest.mark.asyncio
async def test_create_priorities_and_reject_invalid(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    for priority in ("normal", "important", "critical"):
        employee = await _create_employee_api(api_client, hr_a, company_a.id)
        res = await api_client.post(
            "/api/v1/assignments",
            headers=headers,
            json={
                "employee_id": employee["id"],
                "program_id": program_id,
                "priority": priority,
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["priority"] == priority

    employee = await _create_employee_api(api_client, hr_a, company_a.id)
    invalid = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "employee_id": employee["id"],
            "program_id": program_id,
            "priority": "urgent",
        },
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_overdue_derived_on_api(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    past = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    pending = await _create_employee_api(api_client, hr_a, company_a.id)
    pending_res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "employee_id": pending["id"],
            "program_id": program_id,
            "due_at": past,
        },
    )
    assert pending_res.status_code == 201, pending_res.text
    assert pending_res.json()["overdue"] is True
    assert pending_res.json()["status"] == "pending"

    in_progress_emp = await _create_employee_api(api_client, hr_a, company_a.id)
    in_progress_res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "employee_id": in_progress_emp["id"],
            "program_id": program_id,
            "due_at": past,
        },
    )
    assignment_id = in_progress_res.json()["id"]
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.assignments.update(
            assignment_id,
            status=AssignmentStatus.IN_PROGRESS.value,
        )
        await uow.commit()
    got = await api_client.get(f"/api/v1/assignments/{assignment_id}", headers=headers)
    assert got.json()["overdue"] is True

    completed_emp = await _create_employee_api(api_client, hr_a, company_a.id)
    completed_res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "employee_id": completed_emp["id"],
            "program_id": program_id,
            "due_at": past,
        },
    )
    completed_id = completed_res.json()["id"]
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.assignments.update(
            completed_id,
            status=AssignmentStatus.COMPLETED.value,
        )
        await uow.commit()
    got_done = await api_client.get(f"/api/v1/assignments/{completed_id}", headers=headers)
    assert got_done.json()["overdue"] is False

    cancelled_emp = await _create_employee_api(api_client, hr_a, company_a.id)
    cancelled_res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "employee_id": cancelled_emp["id"],
            "program_id": program_id,
            "due_at": past,
        },
    )
    cancelled_id = cancelled_res.json()["id"]
    cancel = await api_client.delete(
        f"/api/v1/assignments/{cancelled_id}",
        headers=headers,
    )
    assert cancel.status_code == 204
    got_cancelled = await api_client.get(
        f"/api/v1/assignments/{cancelled_id}",
        headers=headers,
    )
    assert got_cancelled.json()["overdue"] is False

    future_emp = await _create_employee_api(api_client, hr_a, company_a.id)
    future_res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "employee_id": future_emp["id"],
            "program_id": program_id,
            "due_at": future,
        },
    )
    assert future_res.json()["overdue"] is False

    none_emp = await _create_employee_api(api_client, hr_a, company_a.id)
    none_res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={"employee_id": none_emp["id"], "program_id": program_id},
    )
    assert none_res.json()["overdue"] is False


@pytest.mark.asyncio
async def test_list_orders_by_priority_then_deadline(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    now = datetime.now(UTC)
    specs = [
        ("normal", (now + timedelta(days=1)).isoformat()),
        ("critical", (now + timedelta(days=30)).isoformat()),
        ("important", (now + timedelta(days=2)).isoformat()),
    ]
    created_ids: list[str] = []
    for priority, due in specs:
        employee = await _create_employee_api(api_client, hr_a, company_a.id)
        res = await api_client.post(
            "/api/v1/assignments",
            headers=headers,
            json={
                "employee_id": employee["id"],
                "program_id": program_id,
                "priority": priority,
                "due_at": due,
            },
        )
        assert res.status_code == 201, res.text
        created_ids.append(res.json()["id"])

    listed = await api_client.get(
        "/api/v1/assignments",
        headers=headers,
        params={"company_id": str(company_a.id), "limit": 1000},
    )
    assert listed.status_code == 200
    ids = [row["id"] for row in listed.json() if row["id"] in created_ids]
    assert ids == [created_ids[1], created_ids[2], created_ids[0]]


@pytest.mark.asyncio
async def test_bulk_employees_dedupe_and_compat(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    people = [
        await _create_employee_api(api_client, hr_a, company_a.id) for _ in range(5)
    ]
    ids = [p["id"] for p in people]
    res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "program_id": program_id,
            "employee_ids": [ids[0], ids[1], ids[0]],
            "priority": "important",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["count"] == 2
    assert body["source_batch_id"] is not None
    assert {item["employee_id"] for item in body["items"]} == {ids[0], ids[1]}
    assert all(item["priority"] == "important" for item in body["items"])

    five = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "program_id": program_id,
            "employee_ids": ids[2:],
        },
    )
    assert five.status_code == 201, five.text
    assert five.json()["count"] == 3


@pytest.mark.asyncio
async def test_bulk_rejects_archived_and_cross_tenant_employee(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    employee_b: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    archived = await _create_employee_api(api_client, hr_a, company_a.id)
    arch = await api_client.patch(
        f"/api/v1/employees/{archived['id']}",
        headers=headers,
        json={"status": "archived"},
    )
    assert arch.status_code == 200, arch.text

    archived_res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={"employee_id": archived["id"], "program_id": program_id},
    )
    assert archived_res.status_code == 400, archived_res.text

    foreign = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "program_id": program_id,
            "employee_ids": [str(employee_b.id)],
        },
    )
    assert foreign.status_code == 404, foreign.text


@pytest.mark.asyncio
async def test_department_targeting_snapshot_and_dedupe(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    engineering = await _create_department(
        api_client, hr_a, company_a.id, slug=f"eng-{uuid4().hex[:6]}"
    )
    sales = await _create_department(
        api_client, hr_a, company_a.id, slug=f"sales-{uuid4().hex[:6]}"
    )
    a = await _create_employee_api(api_client, hr_a, company_a.id, name="A")
    b = await _create_employee_api(api_client, hr_a, company_a.id, name="B")
    c = await _create_employee_api(api_client, hr_a, company_a.id, name="C")
    d = await _create_employee_api(api_client, hr_a, company_a.id, name="D")
    extra = await _create_employee_api(api_client, hr_a, company_a.id, name="Sales")
    for person in (a, b, c):
        patched = await api_client.patch(
            f"/api/v1/employees/{person['id']}",
            headers=headers,
            json={"department_id": engineering["id"]},
        )
        assert patched.status_code == 200, patched.text
    sales_patch = await api_client.patch(
        f"/api/v1/employees/{extra['id']}",
        headers=headers,
        json={"department_id": sales["id"]},
    )
    assert sales_patch.status_code == 200

    combined = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "program_id": program_id,
            "department_ids": [engineering["id"], sales["id"]],
            "employee_ids": [b["id"], d["id"]],
            "due_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "deadline_overrides": {d["id"]: (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        },
    )
    assert combined.status_code == 201, combined.text
    body = combined.json()
    recipient_ids = {item["employee_id"] for item in body["items"]}
    assert recipient_ids == {a["id"], b["id"], c["id"], d["id"], extra["id"]}
    assert body["count"] == 5
    by_emp = {item["employee_id"]: item for item in body["items"]}
    assert by_emp[d["id"]]["due_at"] is not None
    assert by_emp[a["id"]]["due_at"] != by_emp[d["id"]]["due_at"]

    later = await _create_employee_api(api_client, hr_a, company_a.id, name="Later")
    join = await api_client.patch(
        f"/api/v1/employees/{later['id']}",
        headers=headers,
        json={"department_id": engineering["id"]},
    )
    assert join.status_code == 200
    listed = await api_client.get(
        f"/api/v1/employees/{later['id']}/assignments",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.asyncio
async def test_inactive_and_cross_tenant_department_rejected(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    admin_b: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    inactive = await _create_department(
        api_client, hr_a, company_a.id, slug=f"old-{uuid4().hex[:6]}"
    )
    off = await api_client.patch(
        f"/api/v1/departments/{inactive['id']}",
        headers=headers,
        json={"is_active": False},
    )
    assert off.status_code == 200
    rejected = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "program_id": program_id,
            "department_ids": [inactive["id"]],
        },
    )
    assert rejected.status_code == 400, rejected.text

    foreign_dept = await _create_department(
        api_client, admin_b, company_b.id, slug=f"b-{uuid4().hex[:6]}"
    )
    leak = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "program_id": program_id,
            "department_ids": [foreign_dept["id"]],
        },
    )
    assert leak.status_code == 404, leak.text


@pytest.mark.asyncio
async def test_bulk_conflict_is_atomic(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    first = await _create_employee_api(api_client, hr_a, company_a.id)
    second = await _create_employee_api(api_client, hr_a, company_a.id)
    created = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={"employee_id": first["id"], "program_id": program_id},
    )
    assert created.status_code == 201

    bulk = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "program_id": program_id,
            "employee_ids": [first["id"], second["id"]],
        },
    )
    assert bulk.status_code == 409, bulk.text
    payload = bulk.json()
    assert "conflicts" in payload
    assert any(c["employee_id"] == first["id"] for c in payload["conflicts"])

    listed = await api_client.get(
        f"/api/v1/employees/{second['id']}/assignments",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.asyncio
async def test_override_must_be_resolved_recipient(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    target = await _create_employee_api(api_client, hr_a, company_a.id)
    other = await _create_employee_api(api_client, hr_a, company_a.id)
    res = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "program_id": program_id,
            "employee_ids": [target["id"]],
            "deadline_overrides": {
                other["id"]: (datetime.now(UTC) + timedelta(days=1)).isoformat()
            },
        },
    )
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_bulk_progress_still_works(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    headers = auth_header(hr_a)
    employee = await _create_employee_api(api_client, hr_a, company_a.id)
    created = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={"program_id": program_id, "employee_ids": [employee["id"]]},
    )
    assert created.status_code == 201, created.text
    assignment_id = created.json()["items"][0]["id"]
    progress = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=headers,
    )
    assert progress.status_code == 200, progress.text
    items = progress.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "not_started"
