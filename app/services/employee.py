from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.tenancy import ensure_same_company

_ALLOWED_ROLES = {item.value for item in EmployeeRole}
_ALLOWED_STATUSES = {item.value for item in EmployeeStatus}


class EmployeeService:
    """Application service for Employee use cases (UnitOfWork + repositories)."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def create_employee(
        self,
        *,
        company_id: UUID,
        actor_company_id: UUID,
        telegram_user_id: int,
        full_name: str,
        telegram_chat_id: int | None = None,
        telegram_username: str | None = None,
        email: str | None = None,
        role: str = EmployeeRole.EMPLOYEE.value,
        status: str = EmployeeStatus.INVITED.value,
        hired_at: date | None = None,
    ) -> Employee:
        self._validate_role(role)
        self._validate_status(status)
        if telegram_user_id <= 0:
            raise ValidationError("telegram_user_id must be a positive integer")
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )

        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")

            try:
                employee = await uow.employees.create(
                    Employee(
                        company_id=company_id,
                        telegram_user_id=telegram_user_id,
                        telegram_chat_id=telegram_chat_id,
                        telegram_username=telegram_username,
                        full_name=full_name,
                        email=email,
                        role=role,
                        status=status,
                        hired_at=hired_at,
                    ),
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Employee with this telegram_user_id already exists in the company"
                ) from exc
            return employee

    async def get_employee(
        self,
        employee_id: UUID,
        *,
        company_id: UUID | None = None,
    ) -> Employee:
        """Load an employee.

        When ``company_id`` is provided, enforce tenant isolation.
        Auth bootstrap may omit it to resolve the token subject.
        """
        async with self._uow_factory() as uow:
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            if company_id is not None:
                ensure_same_company(
                    resource_company_id=employee.company_id,
                    actor_company_id=company_id,
                    not_found_message=f"Employee {employee_id} not found",
                )
            return employee

    async def list_employees(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Employee]:
        if status is not None:
            self._validate_status(status)
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )

        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            return await uow.employees.list_by_company_id(
                company_id,
                offset=offset,
                limit=limit,
                status=status,
            )

    async def get_by_telegram_user_id(
        self,
        *,
        company_id: UUID,
        telegram_user_id: int,
        actor_company_id: UUID | None = None,
    ) -> Employee:
        """Resolve an employee by Telegram identity within a company tenant."""
        if telegram_user_id <= 0:
            raise ValidationError("telegram_user_id must be a positive integer")
        if actor_company_id is not None:
            ensure_same_company(
                resource_company_id=company_id,
                actor_company_id=actor_company_id,
                not_found_message=f"Company {company_id} not found",
            )

        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            employee = await uow.employees.get_by_telegram_user_id(
                company_id,
                telegram_user_id,
            )
            if employee is None:
                raise NotFoundError(
                    f"Employee with telegram_user_id={telegram_user_id} not found"
                )
            return employee

    async def update_employee(
        self,
        employee_id: UUID,
        *,
        company_id: UUID,
        **values: Any,
    ) -> Employee:
        forbidden = {"id", "company_id", "created_at"}
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(f"Cannot update fields: {sorted(extra)}")
        if "role" in values:
            self._validate_role(values["role"])
        if "status" in values:
            self._validate_status(values["status"])
        if "telegram_user_id" in values and values["telegram_user_id"] <= 0:
            raise ValidationError("telegram_user_id must be a positive integer")

        async with self._uow_factory() as uow:
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            ensure_same_company(
                resource_company_id=employee.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {employee_id} not found",
            )
            try:
                updated = await uow.employees.update(employee_id, **values)
                if updated is None:
                    raise NotFoundError(f"Employee {employee_id} not found")
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Employee with this telegram_user_id already exists in the company"
                ) from exc
            return updated

    async def delete_employee(
        self,
        employee_id: UUID,
        *,
        company_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            ensure_same_company(
                resource_company_id=employee.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {employee_id} not found",
            )
            deleted = await uow.employees.delete(employee_id)
            if not deleted:
                raise NotFoundError(f"Employee {employee_id} not found")
            await uow.commit()

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in _ALLOWED_ROLES:
            raise ValidationError(f"Invalid role {role!r}; expected one of {sorted(_ALLOWED_ROLES)}")

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in _ALLOWED_STATUSES:
            raise ValidationError(
                f"Invalid status {status!r}; expected one of {sorted(_ALLOWED_STATUSES)}"
            )
