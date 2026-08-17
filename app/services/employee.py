from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4
import logging

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.security import hash_password, verify_employee_password, verify_password
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
_logger = logging.getLogger("app.employee")


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
        full_name: str,
        telegram_user_id: int | None = None,
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
        # Placeholder until Telegram deep-link bind overwrites it.
        resolved_telegram_id = telegram_user_id
        if resolved_telegram_id is None:
            if status != EmployeeStatus.INVITED.value:
                raise ValidationError("telegram_user_id is required")
            resolved_telegram_id = uuid4().int % 1_000_000_000 + 10_000
        if resolved_telegram_id <= 0:
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
                        telegram_user_id=resolved_telegram_id,
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
                    "Employee with this telegram_user_id or email already exists"
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
        telegram_user_id: int,
        company_id: UUID | None = None,
        actor_company_id: UUID | None = None,
    ) -> Employee:
        """Resolve an employee by Telegram identity.

        Shared-bot path (``company_id`` omitted): platform SELECT by
        ``telegram_user_id``, prefer the unique ACTIVE row, then invited/archived
        for status gates. Tenant is ``employee.company_id`` — never a
        client-supplied company.

        Tenant-scoped path (``company_id`` set): lookup inside that company
        after ``enter_tenant``. Used only for in-tenant uniqueness checks.
        """
        if telegram_user_id <= 0:
            raise ValidationError("telegram_user_id must be a positive integer")
        if company_id is None:
            return await self._resolve_telegram_identity(telegram_user_id)
        if actor_company_id is not None:
            ensure_same_company(
                resource_company_id=company_id,
                actor_company_id=actor_company_id,
                not_found_message=f"Company {company_id} not found",
            )

        async with self._uow_factory() as uow:
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

    async def _resolve_telegram_identity(self, telegram_user_id: int) -> Employee:
        """Global Telegram identity: one active employee, tenant from the row.

        Login has no company_id yet. Resolve under platform SELECT (same class
        as email login). Request/Telegram never supply the tenant.
        """
        async with self._uow_factory() as uow:
            await uow.enter_platform()
            matches = await uow.employees.list_by_telegram_user_id(telegram_user_id)
            if not matches:
                raise NotFoundError(
                    f"Employee with telegram_user_id={telegram_user_id} not found"
                )
            actives = [
                row
                for row in matches
                if row.status == EmployeeStatus.ACTIVE.value
            ]
            if len(actives) > 1:
                raise ConflictError(
                    "Telegram account is linked to multiple active employees"
                )
            if len(actives) == 1:
                return actives[0]
            archived = [
                row
                for row in matches
                if row.status == EmployeeStatus.ARCHIVED.value
            ]
            if archived:
                return archived[0]
            invited = [
                row
                for row in matches
                if row.status == EmployeeStatus.INVITED.value
            ]
            if invited:
                return invited[0]
            raise NotFoundError(
                f"Employee with telegram_user_id={telegram_user_id} not found"
            )

    async def assert_company_active(self, company_id: UUID) -> None:
        """Reject auth when the tenant company or subscription blocks access."""
        async with self._uow_factory() as uow:
            # company_id is from a DB-resolved employee (or bot-bound server config).
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            ensure_company_is_active(company, company_id=company_id)
            await ensure_subscription_allows_access(uow, company_id)

    async def update_own_profile(
        self,
        *,
        employee_id: UUID,
        company_id: UUID,
        full_name: str | None = None,
        email: str | None = None,
    ) -> Employee:
        """Self-service update of allowed personal fields only."""
        values: dict[str, Any] = {}
        if full_name is not None:
            trimmed = full_name.strip()
            if not trimmed:
                raise ValidationError("full_name must not be empty")
            values["full_name"] = trimmed
        if email is not None:
            values["email"] = email.strip().lower() if email.strip() else None
        if not values:
            raise ValidationError("At least one field must be provided for update")

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
                raise ForbiddenError("Only active employees can update their profile")
            try:
                updated = await uow.employees.update(employee_id, **values)
                if updated is None:
                    raise NotFoundError(f"Employee {employee_id} not found")
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Employee with this telegram_user_id or email already exists"
                ) from exc
            _logger.info(
                "profile_changed employee_id=%s company_id=%s fields=%s",
                employee_id,
                company_id,
                sorted(values.keys()),
            )
            return updated

    async def get_company_name(self, company_id: UUID) -> str | None:
        summary = await self.get_company_summary(company_id)
        return summary["name"] if summary else None

    async def get_company_summary(
        self,
        company_id: UUID,
    ) -> dict[str, str | None] | None:
        """Return safe company fields for the authenticated employee's own tenant."""
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                return None
            return {
                "name": company.name,
                "description": company.description,
            }

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
                if values.get("status") == EmployeeStatus.ARCHIVED.value:
                    _logger.info(
                        "employee_archived employee_id=%s company_id=%s actor_role=%s",
                        employee_id,
                        company_id,
                        actor_role,
                    )
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Employee with this telegram_user_id or email already exists"
                ) from exc
            return updated

    async def get_by_email(self, email: str) -> Employee | None:
        """Platform lookup for email login — returns None when not found."""
        normalized = email.strip().lower()
        if not normalized:
            return None
        async with self._uow_factory() as uow:
            # Login has no company_id yet; resolve identity under platform SELECT
            # (same class of auth bootstrap as invite row writes). RLS policies
            # unchanged — no tenant dump beyond the equality filter.
            await uow.enter_platform()
            return await uow.employees.get_by_email(normalized)

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
            if employee.password_hash and verify_password(
                new_password,
                employee.password_hash,
            ):
                raise ValidationError("New password must be different from the current password")

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
            _logger.info(
                "password_changed employee_id=%s company_id=%s",
                employee_id,
                company_id,
            )

    async def initiate_password_reset(
        self,
        *,
        employee_id: UUID,
        company_id: UUID,
        actor_role: str,
    ) -> InviteEmailResult:
        """Admin/HR initiates password reset for a manageable ACTIVE employee."""
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
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            company_name = company.name
            snapshot = SimpleNamespace(
                id=employee.id,
                company_id=employee.company_id,
                full_name=employee.full_name,
                email=employee.email,
                status=employee.status,
            )

        delivery = await self._invites.create_password_reset(
            employee=snapshot,  # type: ignore[arg-type]
            company_name=company_name,
            # Same as onboarding invites: invite rows are written under platform RLS.
            use_platform_rls=True,
        )
        _logger.info(
            "password_reset_initiated employee_id=%s company_id=%s actor_role=%s "
            "delivery=%s",
            employee_id,
            company_id,
            actor_role,
            delivery.delivery,
        )
        return delivery

    async def resend_invite(
        self,
        *,
        employee_id: UUID,
        company_id: UUID,
        actor_role: str,
    ) -> InviteEmailResult:
        """Re-issue invite for an INVITED employee (new token; prior unused invalidated)."""
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
            if employee.status != EmployeeStatus.INVITED.value:
                raise ValidationError("Invite can only be resent for invited employees")
            if not employee.email or not employee.email.strip():
                raise ValidationError("Employee email is required to resend invite")
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            company_name = company.name
            snapshot = employee

        delivery = await self._invites.create_and_send_invite(
            employee=snapshot,
            invited_email=employee.email.strip().lower(),
            company_name=company_name,
            use_platform_rls=True,
        )
        _logger.info(
            "invite_resent employee_id=%s company_id=%s actor_role=%s delivery=%s",
            employee_id,
            company_id,
            actor_role,
            delivery.delivery,
        )
        return delivery

    async def preview_password_reset(self, token: str) -> dict:
        return await self._invites.get_password_reset_preview(token)

    async def confirm_password_reset(self, *, token: str, new_password: str) -> Employee:
        return await self._invites.accept_password_reset(
            token=token,
            new_password=new_password,
        )

    async def delete_employee(
        self,
        employee_id: UUID,
        *,
        company_id: UUID,
        actor_role: str,
    ) -> None:
        """Archive (soft-delete) an employee — preserve assignments/history."""
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
                    "Only company admin can archive admin or hr accounts"
                )
            if employee.status == EmployeeStatus.ARCHIVED.value:
                await uow.enter_session_bootstrap()
                await uow.refresh_sessions.revoke_all_for_subject(
                    subject_type=SUBJECT_EMPLOYEE,
                    subject_id=employee_id,
                )
                await uow.commit()
                return

            updated = await uow.employees.update(
                employee_id,
                status=EmployeeStatus.ARCHIVED.value,
            )
            if updated is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            await uow.enter_session_bootstrap()
            await uow.refresh_sessions.revoke_all_for_subject(
                subject_type=SUBJECT_EMPLOYEE,
                subject_id=employee_id,
            )
            await uow.commit()
            _logger.info(
                "employee_archived employee_id=%s company_id=%s actor_role=%s "
                "via=delete",
                employee_id,
                company_id,
                actor_role,
            )

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
