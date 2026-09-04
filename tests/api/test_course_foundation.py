"""Phase 9D: course lock, revision snapshot, content blocks, completion."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.course_edit_policy import COURSE_LOCKED_MESSAGE
from tests.conftest import _uow_factory, auth_header, unique_telegram_user_id

LOCKED = COURSE_LOCKED_MESSAGE


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
            "title": title or f"Course {uuid4().hex[:8]}",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _add_step(
    client: AsyncClient,
    hr: Employee,
    program_id: str,
    *,
    title: str | None = None,
    content: dict | None = None,
    is_required: bool = True,
    step_type: str = "content",
) -> dict:
    payload: dict = {
        "title": title or f"Step {uuid4().hex[:6]}",
        "step_type": step_type,
        "is_required": is_required,
        "content": content if content is not None else {"body": "Hello"},
    }
    res = await client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=auth_header(hr),
        json=payload,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _publish(client: AsyncClient, hr: Employee, program_id: str) -> dict:
    res = await client.post(
        f"/api/v1/programs/{program_id}/publish",
        headers=auth_header(hr),
    )
    assert res.status_code == 200, res.text
    return res.json()


async def _assign(
    client: AsyncClient,
    hr: Employee,
    *,
    employee_id: str,
    program_id: str,
) -> dict:
    res = await client.post(
        "/api/v1/assignments",
        headers=auth_header(hr),
        json={"employee_id": employee_id, "program_id": program_id},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _get_program(client: AsyncClient, hr: Employee, program_id: str) -> dict:
    res = await client.get(
        f"/api/v1/programs/{program_id}",
        headers=auth_header(hr),
    )
    assert res.status_code == 200, res.text
    return res.json()


async def _extra_employee(company: Company) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company.id,
                telegram_user_id=unique_telegram_user_id(),
                full_name=f"Emp {uuid4().hex[:6]}",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
            ),
        )
        await uow.commit()
        return employee


@pytest.mark.asyncio
async def test_no_assignments_can_add_step(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    assert program["revision"] == 1
    assert program["structure_locked"] is False
    assert program["can_edit_structure"] is True
    step = await _add_step(api_client, hr_a, program["id"])
    assert step["position"] == 0
    got = await _get_program(api_client, hr_a, program["id"])
    assert got["revision"] == 2
    assert got["structure_locked"] is False


@pytest.mark.asyncio
async def test_pending_assignment_locks_structure(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    step = await _add_step(api_client, hr_a, program["id"], title="One")
    await _publish(api_client, hr_a, program["id"])
    assignment = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    assert assignment["status"] == "pending"
    assert assignment["program_revision"] == 2

    got = await _get_program(api_client, hr_a, program["id"])
    assert got["structure_locked"] is True
    assert got["can_edit_structure"] is False

    add = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps",
        headers=auth_header(hr_a),
        json={"title": "Two", "step_type": "content"},
    )
    assert add.status_code == 409
    assert add.json()["detail"] == LOCKED

    patch_content = await api_client.patch(
        f"/api/v1/steps/{step['id']}",
        headers=auth_header(hr_a),
        json={"content": {"body": "changed"}},
    )
    assert patch_content.status_code == 409
    assert patch_content.json()["detail"] == LOCKED

    patch_required = await api_client.patch(
        f"/api/v1/steps/{step['id']}",
        headers=auth_header(hr_a),
        json={"is_required": False},
    )
    assert patch_required.status_code == 409

    reorder = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps/reorder",
        headers=auth_header(hr_a),
        json={"step_ids": [step["id"]]},
    )
    # Single-step reorder is a no-op and does not need to lock.
    assert reorder.status_code == 200

    delete = await api_client.delete(
        f"/api/v1/steps/{step['id']}",
        headers=auth_header(hr_a),
    )
    assert delete.status_code == 409
    assert delete.json()["detail"] == LOCKED

    title_ok = await api_client.patch(
        "/api/v1/programs/" + program["id"],
        headers=auth_header(hr_a),
        json={"title": "Renamed while locked"},
    )
    assert title_ok.status_code == 200, title_ok.text
    assert title_ok.json()["revision"] == 2
    assert title_ok.json()["structure_locked"] is True

    step_title = await api_client.patch(
        f"/api/v1/steps/{step['id']}",
        headers=auth_header(hr_a),
        json={"title": "Cosmetic title"},
    )
    assert step_title.status_code == 200, step_title.text
    still = await _get_program(api_client, hr_a, program["id"])
    assert still["revision"] == 2


@pytest.mark.asyncio
async def test_in_progress_assignment_locks_structure(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    first = await _add_step(api_client, hr_a, program["id"], title="A")
    second = await _add_step(api_client, hr_a, program["id"], title="B")
    await _publish(api_client, hr_a, program["id"])
    assignment = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    progress = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(employee_a),
    )
    assert progress.status_code == 200, progress.text
    by_title = {item["step"]["title"]: item for item in progress.json()["items"]}
    complete = await api_client.post(
        f"/api/v1/progress/{by_title['A']['id']}/complete",
        headers=auth_header(employee_a),
        json={"payload": {}},
    )
    assert complete.status_code == 200, complete.text
    got_asg = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert got_asg.json()["status"] == "in_progress"

    add = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps",
        headers=auth_header(hr_a),
        json={"title": "C", "step_type": "content"},
    )
    assert add.status_code == 409
    reorder = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps/reorder",
        headers=auth_header(hr_a),
        json={"step_ids": [second["id"], first["id"]]},
    )
    assert reorder.status_code == 409
    assert reorder.json()["detail"] == LOCKED


@pytest.mark.asyncio
async def test_completed_and_cancelled_do_not_lock(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(api_client, hr_a, program["id"], title="Only")
    await _publish(api_client, hr_a, program["id"])
    assignment = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    progress = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(employee_a),
    )
    item_id = progress.json()["items"][0]["id"]
    done = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=auth_header(employee_a),
        json={"payload": {}},
    )
    assert done.status_code == 200, done.text
    got_asg = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert got_asg.json()["status"] == "completed"
    got = await _get_program(api_client, hr_a, program["id"])
    assert got["structure_locked"] is False
    extra = await _add_step(api_client, hr_a, program["id"], title="After complete")
    assert extra["title"] == "After complete"

    other = await _extra_employee(company_a)
    pending = await _assign(
        api_client,
        hr_a,
        employee_id=str(other.id),
        program_id=program["id"],
    )
    locked = await _get_program(api_client, hr_a, program["id"])
    assert locked["structure_locked"] is True
    cancel = await api_client.delete(
        f"/api/v1/assignments/{pending['id']}",
        headers=auth_header(hr_a),
    )
    assert cancel.status_code == 204, cancel.text
    unlocked = await _get_program(api_client, hr_a, program["id"])
    assert unlocked["structure_locked"] is False
    await _add_step(api_client, hr_a, program["id"], title="After cancel")


@pytest.mark.asyncio
async def test_one_active_among_many_keeps_lock(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(api_client, hr_a, program["id"])
    await _publish(api_client, hr_a, program["id"])
    first = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    other = await _extra_employee(company_a)
    second = await _assign(
        api_client,
        hr_a,
        employee_id=str(other.id),
        program_id=program["id"],
    )
    cancel = await api_client.delete(
        f"/api/v1/assignments/{first['id']}",
        headers=auth_header(hr_a),
    )
    assert cancel.status_code == 204
    got = await _get_program(api_client, hr_a, program["id"])
    assert got["structure_locked"] is True
    add = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps",
        headers=auth_header(hr_a),
        json={"title": "Nope", "step_type": "content"},
    )
    assert add.status_code == 409
    cancel_last = await api_client.delete(
        f"/api/v1/assignments/{second['id']}",
        headers=auth_header(hr_a),
    )
    assert cancel_last.status_code == 204
    unlocked = await _get_program(api_client, hr_a, program["id"])
    assert unlocked["structure_locked"] is False


@pytest.mark.asyncio
async def test_revision_rules_and_assignment_snapshot(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    assert program["revision"] == 1
    first = await _add_step(api_client, hr_a, program["id"], title="One")
    second = await _add_step(api_client, hr_a, program["id"], title="Two")
    after_steps = await _get_program(api_client, hr_a, program["id"])
    assert after_steps["revision"] == 3

    meta = await api_client.patch(
        f"/api/v1/programs/{program['id']}",
        headers=auth_header(hr_a),
        json={"description": "typo fix"},
    )
    assert meta.status_code == 200
    assert meta.json()["revision"] == 3

    cosmetic_step = await api_client.patch(
        f"/api/v1/steps/{first['id']}",
        headers=auth_header(hr_a),
        json={"title": "One renamed", "estimated_minutes": 5},
    )
    assert cosmetic_step.status_code == 200
    assert (await _get_program(api_client, hr_a, program["id"]))["revision"] == 3

    content = await api_client.patch(
        f"/api/v1/steps/{first['id']}",
        headers=auth_header(hr_a),
        json={"content": {"body": "updated body"}},
    )
    assert content.status_code == 200
    assert (await _get_program(api_client, hr_a, program["id"]))["revision"] == 4

    required = await api_client.patch(
        f"/api/v1/steps/{second['id']}",
        headers=auth_header(hr_a),
        json={"is_required": False},
    )
    assert required.status_code == 200
    assert (await _get_program(api_client, hr_a, program["id"]))["revision"] == 5

    noop = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps/reorder",
        headers=auth_header(hr_a),
        json={"step_ids": [first["id"], second["id"]]},
    )
    assert noop.status_code == 200
    assert (await _get_program(api_client, hr_a, program["id"]))["revision"] == 5

    reorder = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps/reorder",
        headers=auth_header(hr_a),
        json={"step_ids": [second["id"], first["id"]]},
    )
    assert reorder.status_code == 200, reorder.text
    assert (await _get_program(api_client, hr_a, program["id"]))["revision"] == 6

    failed = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps",
        headers=auth_header(hr_a),
        json={"title": "Bad quiz", "step_type": "quiz", "content": {"body": "none"}},
    )
    assert failed.status_code == 400
    assert (await _get_program(api_client, hr_a, program["id"]))["revision"] == 6

    await _publish(api_client, hr_a, program["id"])
    assert (await _get_program(api_client, hr_a, program["id"]))["revision"] == 6

    assignment = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    assert assignment["program_revision"] == 6
    cancel = await api_client.delete(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert cancel.status_code == 204
    await _add_step(api_client, hr_a, program["id"], title="Three")
    assert (await _get_program(api_client, hr_a, program["id"]))["revision"] == 7
    frozen = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert frozen.status_code == 200
    assert frozen.json()["program_revision"] == 6

    other = await _extra_employee(company_a)
    later = await _assign(
        api_client,
        hr_a,
        employee_id=str(other.id),
        program_id=program["id"],
    )
    assert later["program_revision"] == 7
    still_frozen = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert still_frozen.json()["program_revision"] == 6


@pytest.mark.asyncio
async def test_content_blocks_api_and_legacy(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    blocks = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Blocks",
        content={
            "blocks": [
                {"id": "b1", "type": "text", "text": "First"},
                {"id": "b2", "type": "text", "text": "Second"},
            ]
        },
    )
    assert blocks["content_blocks"] == [
        {"id": "b1", "type": "text", "text": "First"},
        {"id": "b2", "type": "text", "text": "Second"},
    ]
    assert blocks["block_count"] == 2
    assert blocks["content"]["blocks"][0]["text"] == "First"

    legacy_body = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Legacy body",
        content={"body": "Old body"},
    )
    assert legacy_body["content"] == {"body": "Old body"}
    assert legacy_body["content_blocks"][0]["text"] == "Old body"

    legacy_text = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Legacy text",
        content={"text": "Old text"},
    )
    assert legacy_text["content_blocks"][0]["text"] == "Old text"

    invalid_type = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps",
        headers=auth_header(hr_a),
        json={
            "title": "Video",
            "step_type": "content",
            "content": {"blocks": [{"type": "video", "text": "nope"}]},
        },
    )
    assert invalid_type.status_code == 400

    not_list = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps",
        headers=auth_header(hr_a),
        json={
            "title": "Bad",
            "step_type": "content",
            "content": {"blocks": "nope"},
        },
    )
    assert not_list.status_code == 400

    missing_text = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps",
        headers=auth_header(hr_a),
        json={
            "title": "Empty item",
            "step_type": "content",
            "content": {"blocks": [{"type": "text"}]},
        },
    )
    assert missing_text.status_code == 400


@pytest.mark.asyncio
async def test_optional_step_does_not_block_completion(
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
        title="Required",
        content={"body": "Must read"},
        is_required=True,
    )
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Optional",
        content={"body": "Nice to have"},
        is_required=False,
    )
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Task",
        step_type="task",
        content={"body": "Do this", "url": "https://example.com"},
    )
    await _publish(api_client, hr_a, program["id"])
    assignment = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    assert assignment["program_revision"] == 4
    progress = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(employee_a),
    )
    by_title = {item["step"]["title"]: item for item in progress.json()["items"]}
    assert by_title["Required"]["step"]["content_blocks"][0]["text"] == "Must read"
    assert by_title["Required"]["block_index"] is None

    req = await api_client.post(
        f"/api/v1/progress/{by_title['Required']['id']}/complete",
        headers=auth_header(employee_a),
        json={"payload": {"block_index": 0}},
    )
    assert req.status_code == 200, req.text
    assert req.json()["block_index"] == 0

    task = await api_client.post(
        f"/api/v1/progress/{by_title['Task']['id']}/complete",
        headers=auth_header(employee_a),
        json={"payload": {}},
    )
    assert task.status_code == 200, task.text

    got = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert got.json()["status"] == "completed"
    leftover = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(hr_a),
    )
    optional = next(
        item
        for item in leftover.json()["items"]
        if item["step"]["title"] == "Optional"
    )
    assert optional["status"] == "not_started"


@pytest.mark.asyncio
async def test_cancel_discards_progress_allows_step_replace_and_reassign(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    """Cancel → discard progress → edit course → reassign from zero."""
    headers = auth_header(hr_a)
    program = await _create_program(api_client, hr_a, company_a)
    old_step = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Old module",
        content={"body": "Revision 1 text"},
    )
    extra_step = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Keep me",
        content={"body": "Also v1"},
    )
    await _publish(api_client, hr_a, program["id"])
    assignment = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    assert assignment["has_structure_snapshot"] is True
    assert "structure_snapshot" not in assignment

    progress = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(employee_a),
    )
    assert progress.status_code == 200
    assert len(progress.json()["items"]) == 2
    first_item = progress.json()["items"][0]
    started = await api_client.post(
        f"/api/v1/progress/{first_item['id']}/complete",
        headers=auth_header(employee_a),
        json={"payload": {}},
    )
    assert started.status_code == 200, started.text
    in_progress = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=headers,
    )
    assert in_progress.json()["status"] == "in_progress"

    cancel = await api_client.delete(
        f"/api/v1/assignments/{assignment['id']}",
        headers=headers,
    )
    assert cancel.status_code == 204, cancel.text

    discarded = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=headers,
    )
    assert discarded.status_code == 200
    assert discarded.json()["items"] == []
    assert discarded.json()["percentage"] == 0
    cancelled = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=headers,
    )
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["has_structure_snapshot"] is True

    unlocked = await _get_program(api_client, hr_a, program["id"])
    assert unlocked["structure_locked"] is False

    removed = await api_client.delete(
        f"/api/v1/steps/{old_step['id']}",
        headers=headers,
    )
    assert removed.status_code == 204, removed.text
    replacement = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="New module",
        content={"body": "Revision 2 text"},
    )
    assert replacement["id"] != old_step["id"]

    listed = await api_client.get(
        f"/api/v1/programs/{program['id']}/steps",
        headers=headers,
    )
    titles = {item["title"] for item in listed.json()}
    assert titles == {"Keep me", "New module"}
    assert extra_step["id"] in {item["id"] for item in listed.json()}

    reassigned = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    assert reassigned["id"] != assignment["id"]
    assert reassigned["status"] == "pending"
    assert reassigned["program_revision"] > assignment["program_revision"]
    fresh = await api_client.get(
        f"/api/v1/assignments/{reassigned['id']}/progress",
        headers=auth_header(employee_a),
    )
    assert fresh.status_code == 200
    items = fresh.json()["items"]
    assert len(items) == 2
    assert {item["status"] for item in items} == {"not_started"}
    assert all(item["completed_at"] is None for item in items)
    assert {item["step"]["title"] for item in items} == {"Keep me", "New module"}
    assert all(item["step"]["content"].get("body") != "Revision 1 text" for item in items)


@pytest.mark.asyncio
async def test_completed_history_keeps_snapshot_after_course_edit(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    headers = auth_header(hr_a)
    program = await _create_program(api_client, hr_a, company_a)
    step = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Handbook",
        content={"body": "Revision 1 handbook"},
    )
    await _publish(api_client, hr_a, program["id"])
    assignment = await _assign(
        api_client,
        hr_a,
        employee_id=str(employee_a.id),
        program_id=program["id"],
    )
    assigned_revision = assignment["program_revision"]
    progress = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(employee_a),
    )
    item_id = progress.json()["items"][0]["id"]
    done = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=auth_header(employee_a),
        json={"payload": {}},
    )
    assert done.status_code == 200, done.text

    patch = await api_client.patch(
        f"/api/v1/steps/{step['id']}",
        headers=headers,
        json={"content": {"body": "Revision 2 handbook"}, "title": "Handbook v2"},
    )
    assert patch.status_code == 200, patch.text
    live = await api_client.get(
        f"/api/v1/programs/{program['id']}/steps",
        headers=headers,
    )
    assert live.json()[0]["content"]["body"] == "Revision 2 handbook"
    assert live.json()[0]["title"] == "Handbook v2"
    current = await _get_program(api_client, hr_a, program["id"])
    assert current["revision"] > assigned_revision

    historical = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=headers,
    )
    assert historical.status_code == 200
    items = historical.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "completed"
    assert items[0]["id"] == item_id
    assert items[0]["step"]["title"] == "Handbook"
    assert items[0]["step"]["content"]["body"] == "Revision 1 handbook"

    frozen = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=headers,
    )
    assert frozen.json()["status"] == "completed"
    assert frozen.json()["program_revision"] == assigned_revision
    assert frozen.json()["has_structure_snapshot"] is True
    assert "structure_snapshot" not in frozen.json()

    blocked = await api_client.delete(
        f"/api/v1/steps/{step['id']}",
        headers=headers,
    )
    assert blocked.status_code == 409
    assert "progress records exist" in blocked.json()["detail"]

