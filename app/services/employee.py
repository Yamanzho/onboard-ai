from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.security import hash_password, verify_employee_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.email import InviteEmailResult
from app.services.platform_management import InviteService
from app.services.refresh_session import SUBJECT_EMPLOYEE
from app.services.subscription_guard import (
    ensure_employee_limit,
    ensure_subscription_allows_access,
)
from app.services.tenancy import ensure_company_is_active, ensure_same_company

_ALLOWED_ROLES = {item.value for item in EmployeeRole}
_ALLOWED_STATUSES = {item.value for item in EmployeeStatus}
_PRIVILEGED_ROLES = frozenset({EmployeeRole.ADMIN.value, EmployeeRole.HR.value})


class EmployeeService:
    """Application service for Employee use cases (UnitOfWork + repositories)."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        invite_service: InviteService | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._invites = invite_service or InviteService(uow_factory=self._uow_factory)

    async def create_employee(
        self,
        *,
        company_id: UUID,
        actor_company_id: UUID,
        actor_role: str,
        telegram_user_id: int,
        full_name: str,
        telegram_chat_id: int | None = None,
        telegram_username: str | None = None,
        email: str | None = None,
        role: str = EmployeeRole.EMPLOYEE.value,
        status: str = EmployeeStatus.INVITED.value,
        hired_at: date | None = None,
    ) -> tuple[Employee, InviteEmailResult | None]:
        self._validate_role(role)
        self._validate_status(status)
        self._assert_can_assign_role(actor_role=actor_role, target_role=role)
        if status == EmployeeStatus.ACTIVE.value:
            raise ValidationError(
                "Cannot create active employees via tenant API; use invite accept"
            )
        if telegram_user_id <= 0:
            raise ValidationError("telegram_user_id must be a positive integer")
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )

        normalized_email = email.strip().lower() if email else None
        if status == EmployeeStatus.INVITED.value and not normalized_email:
            raise ValidationError("email is required when inviting an employee")

        company_name: str
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            company_name = company.name
            await ensure_employee_limit(uow, company_id)

            try:
                employee = await uow.employees.create(
                    Employee(
                        company_id=company_id,
                        telegram_user_id=telegram_user_id,
                        telegram_chat_id=telegram_chat_id,
                        telegram_username=telegram_username,
                        full_name=full_name,
                        email=normalized_email,
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

        delivery: InviteEmailResult | None = None
        if status == EmployeeStatus.INVITED.value and normalized_email:
            # Unified invite infrastructure (same InviteService as Super Admin).
            # Invite table writes stay on platform RLS (no tenant dump of hashes).
            delivery = await self._invites.create_and_send_invite(
                employee=employee,
                invited_email=normalized_email,
                company_name=company_name,
                use_platform_rls=True,
            )
        return employee, delivery

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
            if company_id is None:
                # Pin subject id so auth RLS cannot enumerate/update other rows.
                await uow.enter_auth_bootstrap(employee_id=employee_id)
            else:
                await uow.enter_tenant(company_id)
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
            await uow.enter_tenant(actor_company_id)
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
            # Bot login passes server-validated BOT_COMPANY_ID as company_id.
            await uow.enter_tenant(company_id)
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

    async def assert_company_active(self, company_id: UUID) -> None:
        """Reject auth when the tenant company or subscription blocks access."""
        async with self._uow_factory() as uow:
            # company_id is from a DB-resolved employee (or bot-bound server config).
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            ensure_company_is_active(company, company_id=company_id)
            await ensure_subscription_allows_access(uow, company_id)

    async def update_employee(
        self,
        employee_id: UUID,
        *,
        company_id: UUID,
        actor_role: str,
        **values: Any,
    ) -> Employee:
        forbidden = {"id", "company_id", "created_at", "password_hash"}
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(f"Cannot update fields: {sorted(extra)}")
        if "role" in values:
            self._validate_role(values["role"])
            self._assert_can_assign_role(actor_role=actor_role, target_role=values["role"])
        if "status" in values:
            self._validate_status(values["status"])
        if "telegram_user_id" in values and values["telegram_user_id"] <= 0:
            raise ValidationError("telegram_user_id must be a positive integer")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            ensure_same_company(
                resource_company_id=employee.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {employee_id} not found",
            )
            self._assert_can_manage_target(
                actor_role=actor_role,
                target_role=employee.role,
            )
            if values.get("status") == EmployeeStatus.ACTIVE.value:
                # Activation must go through invite accept (sets password_hash).
                # Admin may reactivate archived accounts only.
                if employee.status != EmployeeStatus.ARCHIVED.value:
                    raise ValidationError(
                        "Activate invited employees via invite accept, not status patch"
                    )
                if actor_role != EmployeeRole.ADMIN.value:
                    raise ForbiddenError("Only company admin can reactivate archived employees")
            try:
                updated = await uow.employees.update(employee_id, **values)
                if updated is None:
                    raise NotFoundError(f"Employee {employee_id} not found")
                # Archive / block: drop this employee's refresh sessions only.
                if values.get("status") == EmployeeStatus.ARCHIVED.value:
                    await uow.enter_session_bootstrap()
                    await uow.refresh_sessions.revoke_all_for_subject(
                        subject_type=SUBJECT_EMPLOYEE,
                        subject_id=employee_id,
                    )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Employee with this telegram_user_id already exists in the company"
                ) from exc
            return updated

    async def change_password(
        self,
        *,
        employee_id: UUID,
        company_id: UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        """Change the authenticated employee's password and revoke all sessions."""
        if len(new_password) < 8:
            raise ValidationError("Password must be at least 8 characters")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            ensure_same_company(
                resource_company_id=employee.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {employee_id} not found",
            )
            if employee.status != EmployeeStatus.ACTIVE.value:
                raise ForbiddenError("Only active employees can change password")
            if not verify_employee_password(
                password=current_password,
                password_hash=employee.password_hash,
            ):
                raise UnauthorizedError("Current password is incorrect")

            updated = await uow.employees.update(
                employee_id,
                password_hash=hash_password(new_password),
            )
            if updated is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            await uow.enter_session_bootstrap()
            await uow.refresh_sessions.revoke_all_for_subject(
                subject_type=SUBJECT_EMPLOYEE,
                subject_id=employee_id,
            )
            await uow.commit()

    async def delete_employee(
        self,
        employee_id: UUID,
        *,
        company_id: UUID,
        actor_role: str,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            ensure_same_company(
                resource_company_id=employee.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {employee_id} not found",
            )
            self._assert_can_manage_target(
                actor_role=actor_role,
                target_role=employee.role,
            )
            if (
                employee.role in _PRIVILEGED_ROLES
                and actor_role != EmployeeRole.ADMIN.value
            ):
                raise ForbiddenError(
                    "Only company admin can delete admin or hr accounts"
                )
            # Hard-delete hygiene: revoke this subject's refresh sessions only.
            await uow.enter_session_bootstrap()
            await uow.refresh_sessions.revoke_all_for_subject(
                subject_type=SUBJECT_EMPLOYEE,
                subject_id=employee_id,
            )
            await uow.enter_tenant(company_id)
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

    @staticmethod
    def _assert_can_assign_role(*, actor_role: str, target_role: str) -> None:
        """Only company admins may create/promote HR or admin accounts."""
        if target_role in _PRIVILEGED_ROLES and actor_role != EmployeeRole.ADMIN.value:
            raise ForbiddenError(
                "Only company admin can assign admin or hr roles"
            )

    @staticmethod
    def _assert_can_manage_target(*, actor_role: str, target_role: str) -> None:
        """HR may only mutate employee accounts — not admin or peer HR.

        Callers must pass the target's *persisted* role loaded from the DB
        before applying PATCH values. This blocks telegram rebind, demotion,
        status changes, and any other field mutation against privileged peers
        (and prevents demote-then-delete bypass).
        """
        if actor_role == EmployeeRole.ADMIN.value:
            return
        if target_role in _PRIVILEGED_ROLES:
            raise ForbiddenError(
                "Only company admin can modify admin or hr accounts"
            )
