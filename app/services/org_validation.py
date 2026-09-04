"""Same-tenant organization invariants shared by employee and topic services."""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import NotFoundError, ValidationError
from app.db.enums import EmployeeStatus
from app.db.uow import UnitOfWork
from app.services.tenancy import ensure_same_company

MAX_MANAGER_CHAIN_DEPTH = 256


async def resolve_department_for_assignment(
    uow: UnitOfWork,
    *,
    department_id: UUID,
    company_id: UUID,
    current_department_id: UUID | None = None,
) -> None:
    department = await uow.departments.get_by_id(department_id)
    if department is None:
        raise NotFoundError(f"Department {department_id} not found")
    ensure_same_company(
        resource_company_id=department.company_id,
        actor_company_id=company_id,
        not_found_message=f"Department {department_id} not found",
    )
    if not department.is_active and department_id != current_department_id:
        raise ValidationError("Cannot assign an inactive department")


async def resolve_employee_for_assignment(
    uow: UnitOfWork,
    *,
    employee_id: UUID,
    company_id: UUID,
    current_employee_id: UUID | None = None,
    allow_non_active: bool = False,
) -> None:
    employee = await uow.employees.get_by_id(employee_id)
    if employee is None:
        raise NotFoundError(f"Employee {employee_id} not found")
    ensure_same_company(
        resource_company_id=employee.company_id,
        actor_company_id=company_id,
        not_found_message=f"Employee {employee_id} not found",
    )
    if allow_non_active:
        return
    keeping_current = current_employee_id is not None and employee_id == current_employee_id
    if employee.status != EmployeeStatus.ACTIVE.value and not keeping_current:
        raise ValidationError("Cannot assign an archived or inactive employee")


async def manager_assignment_would_cycle(
    uow: UnitOfWork,
    *,
    employee_id: UUID,
    manager_id: UUID,
) -> bool:
    """Walk the manager chain from ``manager_id`` looking for ``employee_id``.

    Fail closed if the chain exceeds ``MAX_MANAGER_CHAIN_DEPTH`` (protects
    against pre-existing cycles or unbounded graphs).
    """
    if employee_id == manager_id:
        return True
    seen: set[UUID] = {employee_id}
    current: UUID | None = manager_id
    for _ in range(MAX_MANAGER_CHAIN_DEPTH):
        if current is None:
            return False
        if current in seen:
            return True
        seen.add(current)
        node = await uow.employees.get_by_id(current)
        if node is None:
            return False
        current = node.manager_id
    return True
