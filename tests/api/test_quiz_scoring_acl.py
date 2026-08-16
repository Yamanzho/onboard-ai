"""Quiz scoring is computed on the backend; answer keys are not leaked to employees."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.step_content import public_step_content, score_quiz
from tests.conftest import auth_header


def test_score_quiz_correct_incorrect_and_missing_key() -> None:
    content = {
        "questions": [
            {"id": "q1", "text": "2+2?", "correct": "4"},
            {"id": "q2", "text": "Capital?", "correct": "Astana"},
        ]
    }
    perfect = score_quiz(content, {"q1": "4", "q2": " astana "})
    assert perfect is not None
    assert perfect["correct_count"] == 2
    assert perfect["total"] == 2
    assert perfect["score"] == 1.0

    mixed = score_quiz(content, {"q1": "5", "q2": "Astana"})
    assert mixed is not None
    assert mixed["correct_count"] == 1
    assert mixed["results"][0]["is_correct"] is False

    assert score_quiz({"questions": [{"id": "q1", "text": "open"}]}, {"q1": "x"}) is None
    assert "correct" not in str(public_step_content(content)["questions"])


async def _activate(employee_id) -> None:
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.employees.update(employee_id, status=EmployeeStatus.ACTIVE.value)
        await uow.commit()


async def _employee_headers(
    api_client: AsyncClient,
    hr_headers: dict[str, str],
    company_id,
) -> tuple[dict[str, str], str]:
    emp_res = await api_client.post(
        "/api/v1/employees",
        headers=hr_headers,
        json={
            "company_id": str(company_id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 50,
            "full_name": "Quiz Employee",
            "email": f"quiz-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert emp_res.status_code == 201, emp_res.text
    employee_id = emp_res.json()["id"]
    await _activate(employee_id)
    emp = Employee(
        id=employee_id,
        company_id=company_id,
        telegram_user_id=0,
        full_name="Quiz Employee",
        role=EmployeeRole.EMPLOYEE.value,
        status=EmployeeStatus.ACTIVE.value,
    )
    return auth_header(emp), employee_id


@pytest.mark.asyncio
async def test_quiz_scoring_permissions_and_repeat(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    hr_b: Employee,
) -> None:
    headers = auth_header(hr_a)
    emp_headers, employee_id = await _employee_headers(
        api_client, headers, company_a.id
    )

    program = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={"company_id": str(company_a.id), "title": f"Quiz {uuid4().hex[:6]}"},
    )
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]

    quiz = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={
            "title": "Math",
            "step_type": "quiz",
            "content": {
                "questions": [{"id": "q1", "text": "2+2?", "correct": "4"}],
            },
        },
    )
    assert quiz.status_code == 201, quiz.text
    quiz2 = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={
            "title": "Capital",
            "step_type": "quiz",
            "content": {
                "questions": [{"id": "q1", "text": "2+2 again?", "correct": "4"}],
            },
        },
    )
    assert quiz2.status_code == 201, quiz2.text

    assert (
        await api_client.post(f"/api/v1/programs/{program_id}/publish", headers=headers)
    ).status_code == 200
    assign = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={"employee_id": employee_id, "program_id": program_id},
    )
    assert assign.status_code == 201, assign.text
    assignment_id = assign.json()["id"]

    progress = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=emp_headers,
    )
    assert progress.status_code == 200
    by_title = {row["step"]["title"]: row for row in progress.json()["items"]}
    item = by_title["Math"]
    assert "correct" not in str(item["step"]["content"])

    missing = await api_client.post(
        f"/api/v1/progress/{item['id']}/complete",
        headers=emp_headers,
        json={"payload": {"answers": {}}},
    )
    assert missing.status_code == 400

    wrong = await api_client.post(
        f"/api/v1/progress/{item['id']}/complete",
        headers=emp_headers,
        json={"payload": {"answers": {"q1": "9"}}},
    )
    assert wrong.status_code == 200, wrong.text
    score = wrong.json()["payload"]["quiz_score"]
    assert score["correct_count"] == 0
    assert score["total"] == 1

    repeat = await api_client.post(
        f"/api/v1/progress/{item['id']}/complete",
        headers=emp_headers,
        json={"payload": {"answers": {"q1": "4"}}},
    )
    assert repeat.status_code == 409

    correct = await api_client.post(
        f"/api/v1/progress/{by_title['Capital']['id']}/complete",
        headers=emp_headers,
        json={"payload": {"answers": {"q1": "4"}}},
    )
    assert correct.status_code == 200, correct.text
    assert correct.json()["payload"]["quiz_score"]["correct_count"] == 1

    hr_view = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=headers,
    )
    assert hr_view.status_code == 200
    hr_item = hr_view.json()["items"][0]
    assert hr_item["payload"]["quiz_score"]["correct_count"] == 0
    assert hr_item["step"]["content"]["questions"][0]["correct"] == "4"

    other = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=auth_header(hr_b),
    )
    assert other.status_code == 404
