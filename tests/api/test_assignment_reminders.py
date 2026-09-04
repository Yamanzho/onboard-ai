"""Phase 9G: assignment reminders, outbox idempotency, employee controls."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.reminder import ReminderService
from tests.conftest import _uow_factory, auth_header, unique_telegram_user_id

MORNING = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
AFTERNOON = datetime(2026, 9, 4, 16, 0, tzinfo=UTC)


async def _bind_chat(employee_id: UUID, chat_id: int = 8_900_001) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employees.update(employee_id, telegram_chat_id=chat_id)
        await uow.commit()


async def _create_assigned(
    client: AsyncClient,
    hr: Employee,
    company: Company,
    employee: Employee,
    *,
    priority: str = "normal",
    title: str | None = None,
) -> dict:
    await _bind_chat(employee.id)
    program = await client.post(
        "/api/v1/programs",
        headers=auth_header(hr),
        json={"company_id": str(company.id), "title": title or f"Sec {uuid4().hex[:6]}"},
    )
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]
    step = await client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=auth_header(hr),
        json={
            "title": "Read",
            "step_type": "content",
            "content": {"blocks": [{"id": "b1", "type": "text", "text": "Hi"}]},
        },
    )
    assert step.status_code == 201, step.text
    assert (
        await client.post(
            f"/api/v1/programs/{program_id}/publish",
            headers=auth_header(hr),
        )
    ).status_code == 200
    assigned = await client.post(
        "/api/v1/assignments",
        headers=auth_header(hr),
        json={
            "employee_id": str(employee.id),
            "program_id": program_id,
            "priority": priority,
        },
    )
    assert assigned.status_code == 201, assigned.text
    return assigned.json()


async def _history(client: AsyncClient, hr: Employee, assignment_id: str) -> dict:
    res = await client.get(
        f"/api/v1/assignments/{assignment_id}/notifications",
        headers=auth_header(hr),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _count(history: dict, kind: str) -> int:
    return sum(1 for item in history["items"] if item["source_type"] == kind)


def test_reminder_templates() -> None:
    from app.services.reminder_messages import (
        format_initial_assignment_message,
        format_reminder_message,
    )

    initial = format_initial_assignment_message(
        program_title="InfoSec",
        priority="important",
        due_at=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        timezone_name="UTC",
    )
    assert "InfoSec" in initial
    assert "важный" in initial
    assert "10 сентября" in initial
    critical = format_reminder_message(
        program_title="InfoSec",
        priority="critical",
        due_at=None,
        timezone_name="UTC",
        overdue=True,
    )
    assert critical.startswith("Критично:")
    assert "Срок уже прошёл." in critical


async def test_initial_notification_and_history(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    assignment = await _create_assigned(api_client, hr_a, company_a, employee_a)
    history = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/notifications",
        headers=auth_header(hr_a),
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["preference"]["mode"] == "default"
    kinds = [item["source_type"] for item in body["items"]]
    assert "assignment_initial" in kinds
    assert body["items"][0]["status"] in {"pending", "sending", "sent", "failed"}


async def test_scan_idempotent_and_frequency(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    assignment = await _create_assigned(
        api_client, hr_a, company_a, employee_a, priority="important"
    )
    service = ReminderService()
    first = await service.scan_due(now=MORNING)
    await service.scan_due(now=MORNING)
    history = await _history(api_client, hr_a, assignment["id"])
    assert _count(history, "assignment_reminder") == 1
    assert first["enqueued"] >= 1
    await asyncio.gather(
        service.scan_due(now=AFTERNOON),
        service.scan_due(now=AFTERNOON),
    )
    history = await _history(api_client, hr_a, assignment["id"])
    assert _count(history, "assignment_reminder") == 2

    normal = await _create_assigned(
        api_client, hr_a, company_a, employee_a, priority="normal", title="Normal"
    )
    await service.scan_due(now=MORNING)
    await service.scan_due(now=AFTERNOON)
    normal_history = await _history(api_client, hr_a, normal["id"])
    assert _count(normal_history, "assignment_reminder") == 1


async def test_employee_controls_and_open_does_not_mutate(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    assignment = await _create_assigned(api_client, hr_a, company_a, employee_a)
    emp = auth_header(employee_a)
    ack = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/reminders/acknowledge",
        headers=emp,
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["last_acknowledged_at"] is not None
    listing = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=auth_header(hr_a),
    )
    assert listing.json()["status"] != "completed"
    opened = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=emp,
    )
    assert opened.status_code == 200, opened.text
    opened_pref = (await _history(api_client, hr_a, assignment["id"]))["preference"]
    assert opened_pref["mode"] == "default"

    service = ReminderService()
    await service.acknowledge(
        UUID(assignment["id"]),
        company_id=company_a.id,
        employee_id=employee_a.id,
        now=MORNING,
    )
    before = _count(
        await _history(api_client, hr_a, assignment["id"]), "assignment_reminder"
    )
    await service.scan_due(now=MORNING)
    after_ack = _count(
        await _history(api_client, hr_a, assignment["id"]), "assignment_reminder"
    )
    assert after_ack == before
    await service.scan_due(now=MORNING + timedelta(days=1))
    after_next_day = _count(
        await _history(api_client, hr_a, assignment["id"]), "assignment_reminder"
    )
    assert after_next_day == before + 1

    reduced = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/reminders/reduce",
        headers=emp,
    )
    assert reduced.json()["mode"] == "reduced"
    disabled = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/reminders/disable",
        headers=emp,
    )
    assert disabled.json()["mode"] == "disabled"
    before_disabled = _count(
        await _history(api_client, hr_a, assignment["id"]), "assignment_reminder"
    )
    await service.scan_due(now=MORNING + timedelta(days=2))
    history = await _history(api_client, hr_a, assignment["id"])
    assert history["preference"]["mode"] == "disabled"
    assert _count(history, "assignment_reminder") == before_disabled

    hr_pref = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/reminders/disable",
        headers=auth_header(hr_a),
    )
    assert hr_pref.status_code == 403


async def test_remind_now_cooldown_and_roles(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    assignment = await _create_assigned(api_client, hr_a, company_a, employee_a)
    denied = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/remind-now",
        headers=auth_header(employee_a),
    )
    assert denied.status_code == 403
    first = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/remind-now",
        headers=auth_header(hr_a),
    )
    assert first.status_code == 200, first.text
    assert first.json()["enqueued"] is True
    second = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/remind-now",
        headers=auth_header(hr_a),
    )
    assert second.status_code == 409
    history = (
        await api_client.get(
            f"/api/v1/assignments/{assignment['id']}/notifications",
            headers=auth_header(hr_a),
        )
    ).json()
    assert any(
        item["source_type"] == "assignment_manual_reminder" for item in history["items"]
    )


async def test_remind_now_rejected_when_employee_disabled(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    assignment = await _create_assigned(api_client, hr_a, company_a, employee_a)
    emp = auth_header(employee_a)
    disabled = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/reminders/disable",
        headers=emp,
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["mode"] == "disabled"
    before = await _history(api_client, hr_a, assignment["id"])
    before_ids = [item["id"] for item in before["items"]]
    assert _count(before, "assignment_manual_reminder") == 0
    assert before["preference"]["last_manual_reminder_at"] is None

    hr_now = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/remind-now",
        headers=auth_header(hr_a),
    )
    assert hr_now.status_code == 409
    assert hr_now.json()["detail"] == "Employee disabled reminders for this assignment."

    admin_now = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/remind-now",
        headers=auth_header(admin_a),
    )
    assert admin_now.status_code == 409
    assert admin_now.json()["detail"] == (
        "Employee disabled reminders for this assignment."
    )

    after = await _history(api_client, hr_a, assignment["id"])
    assert after["preference"]["mode"] == "disabled"
    assert after["preference"]["last_manual_reminder_at"] is None
    assert _count(after, "assignment_manual_reminder") == 0
    assert [item["id"] for item in after["items"]] == before_ids


async def test_remind_now_allowed_when_reduced(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    assignment = await _create_assigned(
        api_client, hr_a, company_a, employee_a, title="Reduced remind"
    )
    reduced = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/reminders/reduce",
        headers=auth_header(employee_a),
    )
    assert reduced.status_code == 200, reduced.text
    assert reduced.json()["mode"] == "reduced"
    reminded = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/remind-now",
        headers=auth_header(hr_a),
    )
    assert reminded.status_code == 200, reminded.text
    assert reminded.json()["enqueued"] is True
    history = await _history(api_client, hr_a, assignment["id"])
    assert _count(history, "assignment_manual_reminder") == 1


async def test_completed_and_cancelled_stop(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    assignment = await _create_assigned(api_client, hr_a, company_a, employee_a)
    emp = auth_header(employee_a)
    items = (
        await api_client.get(
            f"/api/v1/assignments/{assignment['id']}/progress",
            headers=emp,
        )
    ).json()["items"]
    item_id = items[0]["id"]
    await api_client.post(f"/api/v1/progress/{item_id}/start", headers=emp)
    done = await api_client.post(
        f"/api/v1/progress/{item_id}/read",
        headers=emp,
        json={"expected_block_index": 0},
    )
    assert done.status_code == 200, done.text
    remind = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/remind-now",
        headers=auth_header(hr_a),
    )
    assert remind.status_code in {400, 409}
    service = ReminderService()
    await service.scan_due(now=MORNING)
    completed_history = await _history(api_client, hr_a, assignment["id"])
    assert _count(completed_history, "assignment_reminder") == 0

    other = await _create_assigned(
        api_client, hr_a, company_a, employee_a, title="Cancel me"
    )
    cancelled = await api_client.delete(
        f"/api/v1/assignments/{other['id']}",
        headers=auth_header(hr_a),
    )
    assert cancelled.status_code == 204
    blocked = await api_client.post(
        f"/api/v1/assignments/{other['id']}/remind-now",
        headers=auth_header(hr_a),
    )
    assert blocked.status_code in {400, 404}
    ack = await api_client.post(
        f"/api/v1/assignments/{other['id']}/reminders/acknowledge",
        headers=emp,
    )
    assert ack.status_code in {400, 404}


async def test_no_telegram_binding_is_skipped(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    other = Employee(
        company_id=company_a.id,
        telegram_user_id=unique_telegram_user_id(),
        full_name="No Chat",
        role=EmployeeRole.EMPLOYEE.value,
        status=EmployeeStatus.ACTIVE.value,
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        other = await uow.employees.create(other)
        await uow.commit()
    assignment = await _create_assigned(api_client, hr_a, company_a, other)
    # _create_assigned binds chat; unbind to simulate skip
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employees.update(other.id, telegram_chat_id=None)
        await uow.commit()
    service = ReminderService()
    await service.scan_due(now=MORNING)
    history = await _history(api_client, hr_a, assignment["id"])
    assert _count(history, "assignment_reminder") == 0


@pytest.mark.security
async def test_employee_cannot_mutate_foreign_reminders(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    other = Employee(
        company_id=company_a.id,
        telegram_user_id=unique_telegram_user_id(),
        full_name="Other Emp",
        role=EmployeeRole.EMPLOYEE.value,
        status=EmployeeStatus.ACTIVE.value,
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        other = await uow.employees.create(other)
        await uow.commit()
    assignment = await _create_assigned(api_client, hr_a, company_a, employee_a)
    denied = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/reminders/disable",
        headers=auth_header(other),
    )
    assert denied.status_code in {403, 404}


async def test_company_notification_window_controls_scan(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    patched = await api_client.patch(
        f"/api/v1/companies/{company_a.id}",
        headers=auth_header(admin_a),
        json={
            "timezone": "UTC",
            "settings": {
                "notifications": {
                    "window_start": "11:00",
                    "window_end": "18:00",
                    "quiet_hours_start": "12:00",
                    "quiet_hours_end": "13:00",
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    notes = patched.json()["settings"]["notifications"]
    assert notes["window_start"] == "11:00"
    assignment = await _create_assigned(api_client, hr_a, company_a, employee_a)
    service = ReminderService()
    await service.scan_due(now=datetime(2026, 9, 4, 10, 30, tzinfo=UTC))
    history = await _history(api_client, hr_a, assignment["id"])
    assert _count(history, "assignment_reminder") == 0
    await service.scan_due(now=datetime(2026, 9, 4, 12, 30, tzinfo=UTC))
    history = await _history(api_client, hr_a, assignment["id"])
    assert _count(history, "assignment_reminder") == 0
    await service.scan_due(now=datetime(2026, 9, 4, 14, 0, tzinfo=UTC))
    history = await _history(api_client, hr_a, assignment["id"])
    assert _count(history, "assignment_reminder") == 1
    invalid = await api_client.patch(
        f"/api/v1/companies/{company_a.id}",
        headers=auth_header(admin_a),
        json={
            "settings": {
                "notifications": {"window_start": "18:00", "window_end": "09:00"}
            }
        },
    )
    assert invalid.status_code == 400
