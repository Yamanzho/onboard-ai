"""Sprint 1.1 — Telegram step content rendering + progress enrichment."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.bot.handlers.step_content import (
    format_step_message,
    render_step_content_body,
    truncate_telegram_html,
)
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from tests.conftest import auth_header, unique_email


def test_render_step_content_body_known_and_empty() -> None:
    assert render_step_content_body(None) == ""
    assert render_step_content_body({}) == ""
    assert render_step_content_body({"body": "  Hello  "}) == "Hello"
    text = render_step_content_body(
        {"body": "Main", "url": "https://example.com", "nested": {"x": 1}, "score": 3}
    )
    assert "Main" in text
    assert "https://example.com" in text
    assert "score: 3" in text
    assert "nested" not in text

    quiz = render_step_content_body(
        {"body": "Quiz intro", "questions": [{"id": "q1", "text": "What?"}]}
    )
    assert "Quiz intro" in quiz
    assert "1. What?" in quiz


def test_format_step_message_includes_title_description_content() -> None:
    msg = format_step_message(
        program_title="Prog",
        percentage=10,
        step_number=1,
        total_steps=2,
        status_label="не начат",
        step_title="Read handbook",
        step_description="Please read carefully",
        step_content={"body": "Chapter 1"},
    )
    assert "Read handbook" in msg
    assert "Please read carefully" in msg
    assert "Chapter 1" in msg
    assert "Prog" in msg


def test_format_step_message_empty_content_ok() -> None:
    msg = format_step_message(
        program_title="Prog",
        percentage=0,
        step_number=1,
        total_steps=1,
        status_label="не начат",
        step_title="Title only",
        step_description=None,
        step_content={},
    )
    assert "Title only" in msg
    assert "кнопку ниже" in msg


def test_truncate_telegram_html() -> None:
    long = "x" * 5000
    out = truncate_telegram_html(long, max_length=100)
    assert len(out) <= 100
    assert out.endswith("…")


@pytest.mark.asyncio
async def test_progress_includes_step_content_and_complete_flow(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    headers = auth_header(hr_a)

    emp_res = await api_client.post(
        "/api/v1/employees",
        headers=headers,
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 20,
            "full_name": "Bot Employee",
            "email": unique_email("bot-employee"),
            "role": "employee",
            "status": "invited",
        },
    )
    assert emp_res.status_code == 201, emp_res.text
    employee_id = emp_res.json()["id"]

    # Activate employee so they can complete progress.
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.employees.update(employee_id, status=EmployeeStatus.ACTIVE.value)
        await uow.commit()

    emp = Employee(
        id=employee_id,
        company_id=company_a.id,
        telegram_user_id=0,
        full_name="Bot Employee",
        role=EmployeeRole.EMPLOYEE.value,
        status=EmployeeStatus.ACTIVE.value,
    )
    emp_headers = auth_header(emp)

    prog = await api_client.post(
        "/api/v1/programs",
        headers=headers,
        json={"company_id": str(company_a.id), "title": f"Onb {uuid4().hex[:6]}"},
    )
    assert prog.status_code == 201
    program_id = prog.json()["id"]

    step1 = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={
            "title": "Welcome step",
            "description": "Intro description",
            "step_type": "content",
            "content": {"body": "Welcome body text"},
        },
    )
    assert step1.status_code == 201, step1.text
    step2 = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=headers,
        json={
            "title": "Second step",
            "step_type": "content",
            "content": {"body": "Second body"},
        },
    )
    assert step2.status_code == 201, step2.text

    assert (
        await api_client.post(f"/api/v1/programs/{program_id}/publish", headers=headers)
    ).status_code == 200

    assign = await api_client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "employee_id": employee_id,
            "program_id": program_id,
            "assigned_by_id": str(hr_a.id),
        },
    )
    assert assign.status_code == 201, assign.text
    assignment_id = assign.json()["id"]

    progress = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=emp_headers,
    )
    assert progress.status_code == 200, progress.text
    body = progress.json()
    assert len(body["items"]) == 2
    by_title = {item["step"]["title"]: item for item in body["items"]}
    assert "Welcome step" in by_title
    first = by_title["Welcome step"]
    assert first["step"]["description"] == "Intro description"
    assert first["step"]["content"]["body"] == "Welcome body text"

    # Peer employee cannot view this assignment progress.
    peer_res = await api_client.post(
        "/api/v1/employees",
        headers=headers,
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 30,
            "full_name": "Peer",
            "email": unique_email("peer"),
            "role": "employee",
            "status": "invited",
        },
    )
    peer_id = peer_res.json()["id"]
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.employees.update(peer_id, status=EmployeeStatus.ACTIVE.value)
        await uow.commit()
    peer = Employee(
        id=peer_id,
        company_id=company_a.id,
        telegram_user_id=0,
        full_name="Peer",
        role=EmployeeRole.EMPLOYEE.value,
        status=EmployeeStatus.ACTIVE.value,
    )
    denied = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=auth_header(peer),
    )
    assert denied.status_code in {403, 404}

    complete = await api_client.post(
        f"/api/v1/progress/{first['id']}/complete",
        headers=emp_headers,
        json={"payload": {"source": "test"}},
    )
    assert complete.status_code == 200, complete.text

    progress2 = await api_client.get(
        f"/api/v1/assignments/{assignment_id}/progress",
        headers=emp_headers,
    )
    by_title2 = {item["step"]["title"]: item for item in progress2.json()["items"]}
    assert by_title2["Welcome step"]["status"] == "completed"
    assert by_title2["Second step"]["status"] != "completed"


@pytest.mark.asyncio
async def test_no_active_assignment_list_empty_for_employee(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    headers = auth_header(hr_a)
    emp_res = await api_client.post(
        "/api/v1/employees",
        headers=headers,
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": uuid4().int % 1_000_000_000 + 40,
            "full_name": "No Assign",
            "email": unique_email("no-assign"),
            "role": "employee",
            "status": "invited",
        },
    )
    employee_id = emp_res.json()["id"]
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.employees.update(employee_id, status=EmployeeStatus.ACTIVE.value)
        await uow.commit()
    emp = Employee(
        id=employee_id,
        company_id=company_a.id,
        telegram_user_id=0,
        full_name="No Assign",
        role=EmployeeRole.EMPLOYEE.value,
        status=EmployeeStatus.ACTIVE.value,
    )
    listed = await api_client.get(
        f"/api/v1/employees/{employee_id}/assignments",
        headers=auth_header(emp),
        params={"status": "in_progress"},
    )
    assert listed.status_code == 200
    assert listed.json() == []
