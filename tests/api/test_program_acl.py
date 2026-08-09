"""SEC-M3: employees must not discover unpublished unassigned programs by UUID."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import AssignmentStatus, EmployeeRole, EmployeeStatus
from app.db.models.assignment import Assignment
from app.db.models.employee import Employee
from app.db.models.onboarding_program import OnboardingProgram
from app.db.models.step import Step
from tests.conftest import auth_header, _uow_factory


async def _create_program(
    company_id,
    *,
    title: str | None = None,
    is_active: bool = False,
    description: str | None = "Draft secret description",
) -> OnboardingProgram:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        program = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_id,
                title=title or f"Program {uuid4().hex[:8]}",
                description=description,
                is_active=is_active,
            ),
        )
        await uow.commit()
        return program


async def _add_step(program_id) -> Step:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        program = await uow.onboarding_programs.get_by_id(program_id)
        assert program is not None
        step = await uow.steps.create(
            Step(
                company_id=program.company_id,
                program_id=program_id,
                title="Step 1",
                step_type="content",
                position=0,
                content={"body": "secret"},
                is_required=True,
            ),
        )
        await uow.commit()
        return step


async def _assign(
    *,
    company_id,
    employee_id,
    program_id,
    status: str = AssignmentStatus.IN_PROGRESS.value,
) -> Assignment:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        assignment = await uow.assignments.create(
            Assignment(
                company_id=company_id,
                employee_id=employee_id,
                program_id=program_id,
                status=status,
                assigned_at=datetime.now(UTC),
            ),
        )
        await uow.commit()
        return assignment


async def test_employee_cannot_get_unpublished_unassigned_program(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    program = await _create_program(company_a.id, is_active=False)

    response = await api_client.get(
        f"/api/v1/programs/{program.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text
    assert "description" not in response.json()
    assert program.description not in response.text


async def test_assigned_employee_can_get_archived_program(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    """Published → assign → archive: assignee may still read metadata (bot UX)."""
    program = await _create_program(
        company_a.id,
        is_active=True,
        description="Assigned program desc",
    )
    await _add_step(program.id)
    await _assign(
        company_id=company_a.id,
        employee_id=employee_a.id,
        program_id=program.id,
    )

    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.onboarding_programs.update(program.id, is_active=False)
        await uow.commit()

    response = await api_client.get(
        f"/api/v1/programs/{program.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(program.id)
    assert body["is_active"] is False
    assert body["description"] == "Assigned program desc"


async def test_cancelled_assignment_does_not_grant_unpublished_program(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    program = await _create_program(company_a.id, is_active=False)
    await _assign(
        company_id=company_a.id,
        employee_id=employee_a.id,
        program_id=program.id,
        status=AssignmentStatus.CANCELLED.value,
    )

    response = await api_client.get(
        f"/api/v1/programs/{program.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text


async def test_employee_can_get_published_program_without_assignment(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    program = await _create_program(
        company_a.id,
        is_active=True,
        description="Published for tenant",
    )

    response = await api_client.get(
        f"/api/v1/programs/{program.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True
    assert response.json()["description"] == "Published for tenant"


async def test_employee_cannot_get_other_tenant_program(
    api_client: AsyncClient,
    company_b,
    employee_a: Employee,
) -> None:
    foreign = await _create_program(company_b.id, is_active=True)

    response = await api_client.get(
        f"/api/v1/programs/{foreign.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text


async def test_employee_cannot_use_peer_assignment_for_unpublished_program(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    """Peer employee's assignment must not unlock unpublished program metadata."""
    async with _uow_factory() as uow:
        await uow.enter_platform()
        peer = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 9300,
                full_name="Peer Assignee",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
            ),
        )
        await uow.commit()

    program = await _create_program(company_a.id, is_active=False)
    await _assign(
        company_id=company_a.id,
        employee_id=peer.id,
        program_id=program.id,
    )

    response = await api_client.get(
        f"/api/v1/programs/{program.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text


async def test_hr_and_admin_can_get_unpublished_program(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
    admin_a: Employee,
) -> None:
    program = await _create_program(
        company_a.id,
        is_active=False,
        description="HR-only draft",
    )

    for actor in (hr_a, admin_a):
        response = await api_client.get(
            f"/api/v1/programs/{program.id}",
            headers=auth_header(actor),
        )
        assert response.status_code == 200, (actor.role, response.text)
        assert response.json()["description"] == "HR-only draft"
        assert response.json()["is_active"] is False


async def test_unpublished_program_does_not_leak_metadata_on_404(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    secret_title = f"SECRET-DRAFT-{uuid4().hex}"
    secret_desc = f"leak-me-{uuid4().hex}"
    program = await _create_program(
        company_a.id,
        title=secret_title,
        description=secret_desc,
        is_active=False,
    )

    response = await api_client.get(
        f"/api/v1/programs/{program.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text
    body = response.json()
    assert secret_title not in response.text
    assert secret_desc not in response.text
    assert "title" not in body or body.get("title") != secret_title
