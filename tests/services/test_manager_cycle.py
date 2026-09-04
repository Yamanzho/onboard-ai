"""Arbitrary-depth manager cycle detection."""

from __future__ import annotations

from uuid import uuid4

from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.org_validation import manager_assignment_would_cycle
from tests.conftest import _uow_factory


async def _create(company_id, *, manager_id=None) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 9000,
                full_name="Cycle Node",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
                manager_id=manager_id,
            ),
        )
        await uow.commit()
        return employee


async def test_self_assignment_is_a_cycle(company_a: Company) -> None:
    employee = await _create(company_a.id)
    async with _uow_factory() as uow:
        await uow.enter_platform()
        assert await manager_assignment_would_cycle(
            uow,
            employee_id=employee.id,
            manager_id=employee.id,
        )


async def test_chain_of_four_detects_loop_back_to_start(company_a: Company) -> None:
    d = await _create(company_a.id)
    c = await _create(company_a.id, manager_id=d.id)
    b = await _create(company_a.id, manager_id=c.id)
    a = await _create(company_a.id, manager_id=b.id)
    async with _uow_factory() as uow:
        await uow.enter_platform()
        assert await manager_assignment_would_cycle(
            uow,
            employee_id=d.id,
            manager_id=a.id,
        )
        assert not await manager_assignment_would_cycle(
            uow,
            employee_id=a.id,
            manager_id=d.id,
        )
