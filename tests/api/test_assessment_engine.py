"""Phase 9E: structured assessment API — retakes, completion, snapshot, keys."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from tests.conftest import _uow_factory, auth_header, unique_telegram_user_id


def _structured_quiz(*, correct: str = "b", extra: list[dict] | None = None) -> dict:
    questions = [
        {
            "id": "q1",
            "type": "single_choice",
            "text": "Capital of Kazakhstan?",
            "options": [
                {"id": "a", "text": "Almaty"},
                {"id": "b", "text": "Astana"},
            ],
            "correct_option_ids": [correct],
        }
    ]
    if extra:
        questions.extend(extra)
    return {"questions": questions, "passing_score": 80}


def _five_question_quiz() -> dict:
    return {
        "passing_score": 80,
        "questions": [
            {
                "id": f"q{index}",
                "type": "single_choice",
                "text": f"Q{index}?",
                "options": [
                    {"id": "a", "text": "Wrong"},
                    {"id": "b", "text": "Right"},
                ],
                "correct_option_ids": ["b"],
            }
            for index in range(1, 6)
        ],
    }


def _answers(correct_count: int, total: int = 5) -> list[dict]:
    return [
        {
            "question_id": f"q{index}",
            "selected_option_ids": ["b" if index <= correct_count else "a"],
        }
        for index in range(1, total + 1)
    ]


async def _create_program(
    client: AsyncClient,
    hr: Employee,
    company: Company,
) -> dict:
    res = await client.post(
        "/api/v1/programs",
        headers=auth_header(hr),
        json={"company_id": str(company.id), "title": f"Assess {uuid4().hex[:6]}"},
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
    step_type: str = "quiz",
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


async def _publish_and_assign(
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


async def _progress_item(
    client: AsyncClient,
    assignment_id: str,
    headers: dict[str, str],
    title: str | None = None,
) -> dict:
    res = await client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    if title is None:
        return items[0]
    by_title = {row["step"]["title"]: row for row in items}
    return by_title[title]


@pytest.mark.asyncio
async def test_structured_quiz_validation_on_create(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    bad = await api_client.post(
        f"/api/v1/programs/{program['id']}/steps",
        headers=auth_header(hr_a),
        json={
            "title": "Bad",
            "step_type": "quiz",
            "content": {
                "questions": [
                    {
                        "id": "q1",
                        "type": "single_choice",
                        "text": "Q",
                        "options": [
                            {"id": "a", "text": "A"},
                            {"id": "b", "text": "B"},
                        ],
                        "correct_option_ids": ["a", "b"],
                    }
                ]
            },
        },
    )
    assert bad.status_code == 400, bad.text
    ok = await _add_step(
        api_client, hr_a, program["id"], title="Good", content=_structured_quiz()
    )
    assert ok["content"]["questions"][0]["correct_option_ids"] == ["b"]


@pytest.mark.asyncio
async def test_retake_sequence_then_block_completed(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client, hr_a, program["id"], title="Exam", content=_five_question_quiz()
    )
    assignment = await _publish_and_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    item_id = (await _progress_item(api_client, assignment["id"], emp))["id"]

    first = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=emp,
        json={"payload": {"answers": _answers(3)}},
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "in_progress"
    assert first.json()["completed_at"] is None
    assert first.json()["payload"]["attempt_count"] == 1
    assert first.json()["payload"]["best_score"] == 60
    assert first.json()["payload"]["passed"] is False
    assert "answers" not in first.json()["payload"]

    second = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=emp,
        json={"payload": {"answers": _answers(3)}},
    )
    assert second.json()["status"] == "in_progress"
    assert second.json()["payload"]["attempt_count"] == 2
    assert second.json()["payload"]["best_score"] == 60

    third = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=emp,
        json={"payload": {"answers": _answers(4)}},
    )
    assert third.status_code == 200, third.text
    assert third.json()["status"] == "completed"
    assert third.json()["payload"]["attempt_count"] == 3
    assert third.json()["payload"]["best_score"] == 80
    assert third.json()["payload"]["passed"] is True

    blocked = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=emp,
        json={"payload": {"answers": _answers(5)}},
    )
    assert blocked.status_code == 409


@pytest.mark.asyncio
async def test_first_attempt_pass_cannot_retake(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client, hr_a, program["id"], title="Easy", content=_structured_quiz()
    )
    assignment = await _publish_and_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    item_id = (await _progress_item(api_client, assignment["id"], emp))["id"]
    passed = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=emp,
        json={
            "payload": {
                "answers": [{"question_id": "q1", "selected_option_ids": ["b"]}]
            }
        },
    )
    assert passed.json()["status"] == "completed"
    assert passed.json()["payload"]["attempt_count"] == 1
    repeat = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=emp,
        json={
            "payload": {
                "answers": [{"question_id": "q1", "selected_option_ids": ["b"]}]
            }
        },
    )
    assert repeat.status_code == 409


@pytest.mark.asyncio
async def test_new_assignment_starts_attempts_from_zero(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client, hr_a, program["id"], title="Exam", content=_structured_quiz()
    )
    first = await _publish_and_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    item_id = (await _progress_item(api_client, first["id"], emp))["id"]
    passed = await api_client.post(
        f"/api/v1/progress/{item_id}/complete",
        headers=emp,
        json={
            "payload": {
                "answers": [{"question_id": "q1", "selected_option_ids": ["b"]}]
            }
        },
    )
    assert passed.json()["payload"]["attempt_count"] == 1
    second = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={"employee_id": str(employee_a.id), "program_id": program["id"]},
    )
    assert second.status_code == 201, second.text
    fresh = await _progress_item(api_client, second.json()["id"], emp)
    assert fresh["status"] != "completed"
    assert not fresh["payload"].get("attempt_count")


@pytest.mark.asyncio
async def test_required_fail_blocks_optional_does_not(
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
        content={"body": "Go"},
        step_type="content",
    )
    await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Required quiz",
        content=_five_question_quiz(),
    )
    assignment = await _publish_and_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    read = await _progress_item(api_client, assignment["id"], emp, "Read")
    quiz = await _progress_item(api_client, assignment["id"], emp, "Required quiz")
    await api_client.post(
        f"/api/v1/progress/{read['id']}/complete",
        headers=emp,
        json={"payload": {}},
    )
    failed = await api_client.post(
        f"/api/v1/progress/{quiz['id']}/complete",
        headers=emp,
        json={"payload": {"answers": _answers(2)}},
    )
    assert failed.json()["status"] == "in_progress"
    listed = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert listed.json()["status"] != "completed"
    passed = await api_client.post(
        f"/api/v1/progress/{quiz['id']}/complete",
        headers=emp,
        json={"payload": {"answers": _answers(5)}},
    )
    assert passed.json()["status"] == "completed"
    done = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert done.json()["status"] == "completed"

    program2 = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client,
        hr_a,
        program2["id"],
        title="Must read",
        content={"body": "Go"},
        step_type="content",
    )
    await _add_step(
        api_client,
        hr_a,
        program2["id"],
        title="Optional quiz",
        content=_five_question_quiz(),
        is_required=False,
    )
    other = await _extra_employee(company_a)
    assignment2 = await _publish_and_assign(
        api_client, hr_a, program_id=program2["id"], employee_id=str(other.id)
    )
    other_h = auth_header(other)
    must = await _progress_item(api_client, assignment2["id"], other_h, "Must read")
    finish = await api_client.post(
        f"/api/v1/progress/{must['id']}/complete",
        headers=other_h,
        json={"payload": {}},
    )
    assert finish.status_code == 200
    closed = await api_client.get(
        f"/api/v1/assignments/{assignment2['id']}",
        headers=auth_header(hr_a),
    )
    assert closed.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_snapshot_scoring_uses_assigned_revision(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    step = await _add_step(
        api_client, hr_a, program["id"], title="Versioned", content=_structured_quiz(correct="b")
    )
    assignment = await _publish_and_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        await uow.steps.update(UUID(step["id"]), content=_structured_quiz(correct="a"))
        await uow.commit()

    emp = auth_header(employee_a)
    item = await _progress_item(api_client, assignment["id"], emp)
    assert "correct_option_ids" not in str(item["step"]["content"])
    v2 = await api_client.post(
        f"/api/v1/progress/{item['id']}/complete",
        headers=emp,
        json={
            "payload": {
                "answers": [{"question_id": "q1", "selected_option_ids": ["a"]}]
            }
        },
    )
    assert v2.json()["status"] == "in_progress"
    assert v2.json()["payload"]["last_score"] == 0
    v1 = await api_client.post(
        f"/api/v1/progress/{item['id']}/complete",
        headers=emp,
        json={
            "payload": {
                "answers": [{"question_id": "q1", "selected_option_ids": ["b"]}]
            }
        },
    )
    assert v1.json()["status"] == "completed"
    assert v1.json()["payload"]["last_score"] == 100

    other = await _extra_employee(company_a)
    later = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={"employee_id": str(other.id), "program_id": program["id"]},
    )
    assert later.status_code == 201, later.text
    other_item = await _progress_item(api_client, later.json()["id"], auth_header(other))
    v2_new = await api_client.post(
        f"/api/v1/progress/{other_item['id']}/complete",
        headers=auth_header(other),
        json={
            "payload": {
                "answers": [{"question_id": "q1", "selected_option_ids": ["a"]}]
            }
        },
    )
    assert v2_new.status_code == 200, v2_new.text
    assert v2_new.json()["status"] == "completed"


@pytest.mark.security
@pytest.mark.asyncio
async def test_employee_payloads_do_not_leak_answer_keys(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    program = await _create_program(api_client, hr_a, company_a)
    await _add_step(
        api_client, hr_a, program["id"], title="Secure", content=_structured_quiz()
    )
    assignment = await _publish_and_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    progress = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=emp,
    )
    assert "correct_option_ids" not in progress.text
    item = progress.json()["items"][0]
    completed = await api_client.post(
        f"/api/v1/progress/{item['id']}/complete",
        headers=emp,
        json={
            "payload": {
                "answers": [{"question_id": "q1", "selected_option_ids": ["b"]}]
            }
        },
    )
    assert completed.status_code == 200
    assert "correct_option_ids" not in completed.text
    assert "answers" not in completed.json()["payload"]
    assert "results" not in (completed.json()["payload"].get("quiz_score") or {})

    hr_view = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(hr_a),
    )
    assert hr_view.json()["items"][0]["step"]["content"]["questions"][0][
        "correct_option_ids"
    ] == ["b"]
    frozen = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert "structure_snapshot" not in frozen.json()
    assert frozen.json().get("has_structure_snapshot") is True


@pytest.mark.asyncio
async def test_legacy_quiz_still_completes_on_any_answer(
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
        title="Legacy",
        content={"questions": [{"id": "q1", "text": "2+2?", "correct": "4"}]},
    )
    assignment = await _publish_and_assign(
        api_client, hr_a, program_id=program["id"], employee_id=str(employee_a.id)
    )
    emp = auth_header(employee_a)
    item = await _progress_item(api_client, assignment["id"], emp)
    wrong = await api_client.post(
        f"/api/v1/progress/{item['id']}/complete",
        headers=emp,
        json={"payload": {"answers": {"q1": "9"}}},
    )
    assert wrong.status_code == 200
    assert wrong.json()["status"] == "completed"
    assert wrong.json()["payload"]["quiz_score"]["correct_count"] == 0
