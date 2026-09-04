"""Phase 9F: content-block progression, resume, snapshot order, quiz transition."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.learning_progress import (
    current_block_index,
    is_final_block,
    resolve_resume_item,
)
from tests.conftest import _uow_factory, auth_header, unique_telegram_user_id


def _blocks(*texts: str) -> dict:
    return {
        "blocks": [
            {"id": f"b{index}", "type": "text", "text": text}
            for index, text in enumerate(texts, start=1)
        ]
    }


async def _create_program(
    client: AsyncClient,
    hr: Employee,
    company: Company,
    *,
    title: str | None = None,
) -> dict:
    res = await client.post(
        "/api/v1/programs",
        headers=auth_header(hr),
        json={
            "company_id": str(company.id),
            "title": title or f"Learn {uuid4().hex[:6]}",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _add_step(
    client: AsyncClient,
    hr: Employee,
    program_id: str,
    *,
    title: str,
    content: dict,
    step_type: str = "content",
    is_required: bool = True,
) -> dict:
    res = await client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=auth_header(hr),
        json={
            "title": title,
            "step_type": step_type,
            "is_required": is_required,
            "content": content,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _publish_assign(
    client: AsyncClient,
    hr: Employee,
    *,
    program_id: str,
    employee_id: str,
) -> dict:
    assert (
        await client.post(
            f"/api/v1/programs/{program_id}/publish",
            headers=auth_header(hr),
        )
    ).status_code == 200
    res = await client.post(
        "/api/v1/assignments",
        headers=auth_header(hr),
        json={"employee_id": employee_id, "program_id": program_id},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _items(
    client: AsyncClient,
    assignment_id: str,
    headers: dict[str, str],
) -> list[dict]:
    res = await client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "program_id" in body
    return body["items"]


def test_block_index_helpers() -> None:
    assert current_block_index(None) == 0
    assert current_block_index({"block_index": 2}) == 2
    assert is_final_block(0, 1) is True
    assert is_final_block(1, 3) is False
    assert is_final_block(2, 3) is True
    assert is_final_block(0, 0) is True


def test_resolve_resume_prefers_in_progress() -> None:
    class Row:
        def __init__(self, status: str) -> None:
            self.status = status

    items = [Row("not_started"), Row("in_progress"), Row("completed")]
    assert resolve_resume_item(items).status == "in_progress"
    items = [Row("not_started"), Row("not_started")]
    assert resolve_resume_item(items).status == "not_started"


async def test_three_block_flow_and_final_read(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Passwords",
        content=_blocks("One", "Two", "Three"),
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    headers = auth_header(employee_a)
    item = (await _items(api_client, assignment["id"], headers))[0]
    item_id = item["id"]
    assert item["block_index"] is None
    assert item["status"] == "not_started"

    started = await api_client.post(
        f"/api/v1/progress/{item_id}/start",
        headers=headers,
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_progress"
    assert started.json()["payload"]["block_index"] == 0
    assert started.json()["payload"]["content_started"] is True

    again = await api_client.post(
        f"/api/v1/progress/{item_id}/start",
        headers=headers,
    )
    assert again.json()["payload"]["block_index"] == 0

    nxt = await api_client.post(
        f"/api/v1/progress/{item_id}/advance",
        headers=headers,
        json={"expected_block_index": 0},
    )
    assert nxt.status_code == 200, nxt.text
    assert nxt.json()["payload"]["block_index"] == 1
    assert nxt.json()["status"] == "in_progress"

    nxt = await api_client.post(
        f"/api/v1/progress/{item_id}/advance",
        headers=headers,
        json={"expected_block_index": 1},
    )
    assert nxt.json()["payload"]["block_index"] == 2

    done = await api_client.post(
        f"/api/v1/progress/{item_id}/read",
        headers=headers,
        json={"expected_block_index": 2},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    refreshed = (await _items(api_client, assignment["id"], headers))[0]
    assert refreshed["status"] == "completed"
    assert refreshed["block_index"] == 2


async def test_advance_idempotency_and_stale_callback(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Blocks",
        content=_blocks("A", "B", "C"),
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    headers = auth_header(employee_a)
    item_id = (await _items(api_client, assignment["id"], headers))[0]["id"]
    await api_client.post(f"/api/v1/progress/{item_id}/start", headers=headers)
    first = await api_client.post(
        f"/api/v1/progress/{item_id}/advance",
        headers=headers,
        json={"expected_block_index": 0},
    )
    assert first.json()["payload"]["block_index"] == 1
    dup = await api_client.post(
        f"/api/v1/progress/{item_id}/advance",
        headers=headers,
        json={"expected_block_index": 0},
    )
    assert dup.json()["payload"]["block_index"] == 1
    stale_read = await api_client.post(
        f"/api/v1/progress/{item_id}/read",
        headers=headers,
        json={"expected_block_index": 0},
    )
    assert stale_read.json()["status"] == "in_progress"
    assert stale_read.json()["payload"]["block_index"] == 1


async def test_double_final_read_is_conflict(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="One",
        content=_blocks("Only"),
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    headers = auth_header(employee_a)
    item_id = (await _items(api_client, assignment["id"], headers))[0]["id"]
    await api_client.post(f"/api/v1/progress/{item_id}/start", headers=headers)
    first = await api_client.post(
        f"/api/v1/progress/{item_id}/read",
        headers=headers,
        json={"expected_block_index": 0},
    )
    assert first.json()["status"] == "completed"
    second = await api_client.post(
        f"/api/v1/progress/{item_id}/read",
        headers=headers,
        json={"expected_block_index": 0},
    )
    assert second.status_code == 409


async def test_cancelled_and_completed_cannot_mutate(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    headers = auth_header(hr_a)
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Read",
        content=_blocks("Hi"),
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    item_id = (await _items(api_client, assignment["id"], emp))[0]["id"]
    await api_client.post(f"/api/v1/progress/{item_id}/start", headers=emp)
    await api_client.post(
        f"/api/v1/progress/{item_id}/read",
        headers=emp,
        json={"expected_block_index": 0},
    )
    completed_id = item_id
    reopen = await api_client.post(
        f"/api/v1/progress/{completed_id}/start",
        headers=emp,
    )
    assert reopen.status_code == 409

    program2 = await _create_program(api_client, hr_a, company_a, title="Cancel me")
    await _add_step(
        api_client,
        hr_a,
        program2["id"],
        title="Soon gone",
        content=_blocks("X", "Y"),
    )
    other = await _publish_assign(
        api_client, hr_a, program_id=program2["id"], employee_id=str(employee_a.id)
    )
    other_item = (await _items(api_client, other["id"], emp))[0]["id"]
    await api_client.post(f"/api/v1/progress/{other_item}/start", headers=emp)
    cancelled = await api_client.delete(
        f"/api/v1/assignments/{other['id']}",
        headers=headers,
    )
    assert cancelled.status_code == 204
    blocked = await api_client.post(
        f"/api/v1/progress/{other_item}/advance",
        headers=emp,
        json={"expected_block_index": 0},
    )
    assert blocked.status_code in {400, 404}


async def test_snapshot_content_and_order(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    first = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Alpha",
        content=_blocks("v1-a"),
    )
    second = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Beta",
        content=_blocks("v1-b"),
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    items = await _items(api_client, assignment["id"], emp)
    assert [row["step"]["title"] for row in items] == ["Alpha", "Beta"]
    assert items[0]["step"]["content_blocks"][0]["text"] == "v1-a"

    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        await uow.steps.update(
            UUID(first["id"]),
            title="Alpha-v2",
            content={"blocks": [{"id": "n", "type": "text", "text": "v2-a"}]},
        )
        await uow.steps.update(
            UUID(second["id"]),
            title="Beta-v2",
            content={"blocks": [{"id": "n", "type": "text", "text": "v2-b"}]},
        )
        await uow.commit()

    items = await _items(api_client, assignment["id"], emp)
    assert [row["step"]["title"] for row in items] == ["Alpha", "Beta"]
    assert items[0]["step"]["content_blocks"][0]["text"] == "v1-a"
    assert items[1]["step"]["content_blocks"][0]["text"] == "v1-b"


async def test_content_then_quiz_pass_completes_assignment(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Read",
        content=_blocks("Policy"),
    )
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Quiz",
        step_type="quiz",
        content={
            "passing_score": 80,
            "questions": [
                {
                    "id": "q1",
                    "type": "single_choice",
                    "text": "Ok?",
                    "options": [
                        {"id": "a", "text": "No"},
                        {"id": "b", "text": "Yes"},
                    ],
                    "correct_option_ids": ["b"],
                }
            ],
        },
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    by_title = {
        row["step"]["title"]: row
        for row in await _items(api_client, assignment["id"], emp)
    }
    read_id = by_title["Read"]["id"]
    quiz_id = by_title["Quiz"]["id"]
    await api_client.post(f"/api/v1/progress/{read_id}/start", headers=emp)
    await api_client.post(
        f"/api/v1/progress/{read_id}/read",
        headers=emp,
        json={"expected_block_index": 0},
    )
    items = await _items(api_client, assignment["id"], emp)
    assert items[0]["status"] == "completed"
    assert items[1]["status"] == "not_started"

    fail = await api_client.post(
        f"/api/v1/progress/{quiz_id}/complete",
        headers=emp,
        json={"payload": {"answers": [{"question_id": "q1", "selected_option_ids": ["a"]}]}},
    )
    assert fail.json()["status"] == "in_progress"
    listing = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert listing.json()["status"] != "completed"

    passed = await api_client.post(
        f"/api/v1/progress/{quiz_id}/complete",
        headers=emp,
        json={"payload": {"answers": [{"question_id": "q1", "selected_option_ids": ["b"]}]}},
    )
    assert passed.json()["status"] == "completed"
    listing = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert listing.json()["status"] == "completed"
    resume = await api_client.post(
        f"/api/v1/progress/{read_id}/start",
        headers=emp,
    )
    assert resume.status_code in {400, 409}


async def test_optional_step_does_not_block_and_cannot_resume_after_done(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Must",
        content=_blocks("Required"),
    )
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Extra",
        content=_blocks("Optional"),
        is_required=False,
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    by_title = {
        row["step"]["title"]: row
        for row in await _items(api_client, assignment["id"], emp)
    }
    await api_client.post(
        f"/api/v1/progress/{by_title['Must']['id']}/start", headers=emp
    )
    await api_client.post(
        f"/api/v1/progress/{by_title['Must']['id']}/read",
        headers=emp,
        json={"expected_block_index": 0},
    )
    listing = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert listing.json()["status"] == "completed"
    extra = await api_client.post(
        f"/api/v1/progress/{by_title['Extra']['id']}/start",
        headers=emp,
    )
    assert extra.status_code in {400, 409}


async def test_reassign_starts_blocks_from_zero(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Mod",
        content=_blocks("A", "B"),
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    item_id = (await _items(api_client, assignment["id"], emp))[0]["id"]
    await api_client.post(f"/api/v1/progress/{item_id}/start", headers=emp)
    await api_client.post(
        f"/api/v1/progress/{item_id}/advance",
        headers=emp,
        json={"expected_block_index": 0},
    )
    assert (
        await api_client.delete(
            f"/api/v1/assignments/{assignment['id']}",
            headers=auth_header(hr_a),
        )
    ).status_code == 204
    again = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    fresh = (await _items(api_client, again["id"], emp))[0]
    assert fresh["status"] == "not_started"
    assert fresh["block_index"] is None


@pytest.mark.security
async def test_employee_cannot_mutate_foreign_progress(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    other = Employee(
        company_id=company_a.id,
        telegram_user_id=unique_telegram_user_id(),
        full_name="Other",
        role=EmployeeRole.EMPLOYEE.value,
        status=EmployeeStatus.ACTIVE.value,
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        other = await uow.employees.create(other)
        await uow.commit()

    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Secret",
        content=_blocks("No"),
    )
    assignment = await _publish_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    item_id = (await _items(api_client, assignment["id"], auth_header(employee_a)))[0][
        "id"
    ]
    denied = await api_client.post(
        f"/api/v1/progress/{item_id}/start",
        headers=auth_header(other),
    )
    assert denied.status_code in {403, 404}
