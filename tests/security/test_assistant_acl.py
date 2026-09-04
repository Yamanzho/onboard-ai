"""Assistant reads only the authenticated employee's tenant data."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models.company import Company
from app.db.models.department import Department
from app.db.models.employee import Employee
from app.db.models.question_topic import QuestionTopic
from app.db.models.topic_responsibility import TopicResponsibility
from app.services.assistant.orchestrator import AssistantOrchestrator
from tests.conftest import _uow_factory, auth_header


@pytest.mark.security
@pytest.mark.asyncio
async def test_assistant_cannot_see_other_employee_assignments(
    api_client,
    hr_a: Employee,
    employee_a: Employee,
    company_a: Company,
) -> None:
    other = await _create_peer(company_a.id)
    program = await api_client.post(
        "/api/v1/programs",
        headers=auth_header(hr_a),
        json={"company_id": str(company_a.id), "title": "Secret course"},
    )
    assert program.status_code == 201
    await api_client.post(
        f"/api/v1/programs/{program.json()['id']}/steps",
        headers=auth_header(hr_a),
        json={
            "title": "Hidden",
            "step_type": "content",
            "content": {"blocks": [{"id": "b1", "type": "text", "text": "peer only"}]},
        },
    )
    assert (
        await api_client.post(
            f"/api/v1/programs/{program.json()['id']}/publish",
            headers=auth_header(hr_a),
        )
    ).status_code == 200
    assigned = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={
            "employee_id": str(other.id),
            "program_id": program.json()["id"],
        },
    )
    assert assigned.status_code == 201
    orch = AssistantOrchestrator(uow_factory=_uow_factory)
    mine = await orch.handle(
        "Что мне делать?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert "Secret course" not in mine.text
    peer = await orch.handle(
        "Что мне делать?",
        actor_company_id=other.company_id,
        actor_employee_id=other.id,
        actor_role=other.role,
    )
    assert "Secret course" in peer.text


@pytest.mark.security
@pytest.mark.asyncio
async def test_responsibility_is_tenant_scoped(
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        dept = await uow.departments.create(
            Department(
                company_id=company_b.id,
                name="Foreign IT",
                slug=f"it-{uuid4().hex[:6]}",
                is_active=True,
            )
        )
        topic = await uow.question_topics.create(
            QuestionTopic(
                company_id=company_b.id,
                name="Ноутбуки",
                slug="laptops",
                is_active=True,
            )
        )
        await uow.topic_responsibilities.create(
            TopicResponsibility(
                company_id=company_b.id,
                topic_id=topic.id,
                department_id=dept.id,
                employee_id=employee_b.id,
            )
        )
        await uow.commit()

    orch = AssistantOrchestrator(uow_factory=_uow_factory)
    result = await orch.handle(
        "Кто отвечает за ноутбуки?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert "Foreign IT" not in result.text
    assert employee_b.full_name not in result.text


async def _create_peer(company_id) -> Employee:
    from app.db.enums import EmployeeRole, EmployeeStatus
    from tests.conftest import unique_telegram_user_id

    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=unique_telegram_user_id(),
                full_name="Peer Employee",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
            )
        )
        await uow.commit()
        return employee
