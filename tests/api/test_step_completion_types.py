"""Step type completion must be validated end-to-end."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.step_content import parse_questions, validate_completion_payload
from tests.conftest import auth_header


def test_parse_questions_and_ack_validation() -> None:
    assert parse_questions({"questions": ["One", {"id": "q2", "text": "Two"}]}) == [
        {"id": "q1", "text": "One"},
        {"id": "q2", "text": "Two"},
    ]
    validate_completion_payload("ack", {}, {"ack": True})
    with pytest.raises(Exception):
        validate_completion_payload("ack", {}, {"ack": False})


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
            "full_name": "Step Employee",
            "email": f"step-{uuid4().hex[:8]}@example.com",
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
        full_name="Step Employee",
        role=EmployeeRole.EMPLOYEE.value,
        status=EmployeeStatus.ACTIVE.value,
    )
    return auth_header(emp), employee_id


@pytest.mark.asyncio
async def test_ack_and_quiz_completion_rules(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = auth_header(hr_a)
    emp_headers, employee_id = await _employee_headers(
        api_client, headers, company_a.id
    )

    program = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={"company_id": str(company_a.id), "title": f"Types {uuid4().hex[:6]}"},
    )
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]

    quiz_reject = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={"title": "Empty quiz", "step_type": "quiz", "content": {"body": "no q"}},
    )
    assert quiz_reject.status_code == 400, quiz_reject.text

    ack = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={
            "title": "Policy",
            "step_type": "ack",
            "content": {"body": "Please confirm"},
        },
    )
    assert ack.status_code == 201, ack.text
    quiz = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={
            "title": "Quiz",
            "step_type": "quiz",
            "content": {
                "body": "Answer",
                "questions": [
                    {
                        "id": "q1",
                        "text": "What is 2+2?",
                        "correct": "4",
                    }
                ],
            },
        },
    )
    assert quiz.status_code == 201, quiz.text

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
    assert progress.status_code == 200, progress.text
    by_title = {item["step"]["title"]: item for item in progress.json()["items"]}

    denied_ack = await api_client.post(
        f"/api/v1/progress/{by_title['Policy']['id']}/complete",
        headers=emp_headers,
        json={"payload": {"source": "web"}},
    )
    assert denied_ack.status_code == 400, denied_ack.text

    ok_ack = await api_client.post(
        f"/api/v1/progress/{by_title['Policy']['id']}/complete",
        headers=emp_headers,
        json={"payload": {"ack": True}},
    )
    assert ok_ack.status_code == 200, ok_ack.text

    denied_quiz = await api_client.post(
        f"/api/v1/progress/{by_title['Quiz']['id']}/complete",
        headers=emp_headers,
        json={"payload": {"ack": True}},
    )
    assert denied_quiz.status_code == 400, denied_quiz.text

    service_token = "phase-7d-unit-test-bot-service-token"
    monkeypatch.setattr(get_settings(), "bot_service_token", service_token)
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.employees.update(
            employee_id,
            telegram_chat_id=8_800_001,
        )
        await uow.commit()
    ok_quiz = await api_client.post(
        f"/api/v1/progress/{by_title['Quiz']['id']}/complete",
        headers={
            **emp_headers,
            "X-Telegram-Delivery": "durable",
            "X-Bot-Service-Token": service_token,
        },
        json={"payload": {"answers": {"q1": "4"}}},
    )
    assert ok_quiz.status_code == 200, ok_quiz.text
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        outbound = await uow.telegram_outbound.get_by_source(
            source_type="quiz_result",
            source_key=by_title["Quiz"]["id"],
        )
        assert outbound is not None
        assert outbound.chat_id == 8_800_001
        assert outbound.body == "Результат теста: 1 из 1."

    done = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=emp_headers,
    )
    assert done.status_code == 200
    assert done.json()["percentage"] == 100.0
