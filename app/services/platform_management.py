from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password, hash_token
from app.db.enums import (
    EmployeeRole,
    EmployeeStatus,
    PaymentStatus,
    PlatformAuditAction,
    SubscriptionHistoryEventType,
    SubscriptionStatus,
    SubscriptionTier,
)
from app.db.models.company import Company
from app.db.models.company_subscription import CompanySubscription
from app.db.models.employee import Employee
from app.db.models.employee_invite import EmployeeInvite
from app.db.models.platform_audit_log import PlatformAuditLog
from app.db.models.subscription_history import SubscriptionHistoryEvent
from app.db.uow import UnitOfWork
from app.services.email import EmailService
from app.services.refresh_session import SUBJECT_EMPLOYEE

TIER_LIMITS: dict[str, dict[str, int]] = {
    SubscriptionTier.STARTER.value: {"employees": 10, "programs": 3},
    SubscriptionTier.PROFESSIONAL.value: {"employees": 50, "programs": 20},
    SubscriptionTier.ENTERPRISE.value: {"employees": 9999, "programs": 9999},
}

_TRIAL_DAYS = 14


def tier_limits(tier: str) -> dict[str, int]:
    return TIER_LIMITS.get(tier, TIER_LIMITS[SubscriptionTier.STARTER.value])


class PlatformAuditMixin:
    async def _record_audit(
        self,
        uow: UnitOfWork,
        *,
        super_admin_id: UUID | None,
        action: str,
        resource_type: str,
        summary: str,
        resource_id: UUID | None = None,
        company_id: UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        await uow.platform_audit_logs.create(
            PlatformAuditLog(
                super_admin_id=super_admin_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                company_id=company_id,
                summary=summary,
                details=details or {},
            ),
        )


class InviteService(PlatformAuditMixin):
    def __init__(
        self,
        uow_factory=UnitOfWork,
        email_service: EmailService | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._email = email_service or EmailService()

    async def create_and_send_invite(
        self,
        *,
        employee: Employee,
        invited_email: str,
        company_name: str,
        super_admin_id: UUID | None = None,
    ) -> None:
        # Onboarding invites are for INVITED users only — never ACTIVE password reset.
        if employee.status != EmployeeStatus.INVITED.value:
            raise ValidationError(
                "Onboarding invites can only be sent to invited employees"
            )

        settings = get_settings()
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=settings.invite_ttl_hours)
        normalized_email = invited_email.strip().lower()

        async with self._uow_factory() as uow:
            await uow.enter_platform()
            # Invalidate prior unused invites so resend cannot leave password-reset
            # tokens that overwrite a later-accepted password.
            await uow.employee_invites.invalidate_unused_for_employee(employee.id)
            await uow.employee_invites.create(
                EmployeeInvite(
                    company_id=employee.company_id,
                    employee_id=employee.id,
                    token_hash=hash_token(token),
                    expires_at=expires_at,
                    invited_email=normalized_email,
                    created_by_super_admin_id=super_admin_id,
                ),
            )
            if employee.email != normalized_email:
                await uow.employees.update(employee.id, email=normalized_email)
            await uow.commit()

        # Fragment carries the secret so browsers/proxies do not put it in path
        # access logs or Referer (SPA reads location.hash; preview uses POST body).
        invite_url = f"{settings.invite_base_url.rstrip('/')}/invite#{token}"
        await self._email.send_invite_email(
            to_email=normalized_email,
            full_name=employee.full_name,
            invite_url=invite_url,
            company_name=company_name,
        )

    async def get_invite_preview(self, token: str) -> dict[str, Any]:
        token_hash = hash_token(token)
        async with self._uow_factory() as uow:
            # Pin token_hash so auth RLS cannot enumerate other invites.
            await uow.enter_auth_bootstrap(invite_token_hash=token_hash)
            invite = await uow.employee_invites.get_by_token_hash(token_hash)
            if invite is None:
                raise NotFoundError("Invite not found")
            if invite.used_at is not None:
                raise ValidationError("Invite already used")
            if invite.expires_at < datetime.now(UTC):
                raise ValidationError("Invite expired")

            # Pin invite.employee_id (from DB invite row, not client input).
            await uow.enter_auth_bootstrap(employee_id=invite.employee_id)
            employee = await uow.employees.get_by_id(invite.employee_id)
            if employee is None:
                raise NotFoundError("Employee not found")
            if employee.status != EmployeeStatus.INVITED.value:
                raise ValidationError(
                    "Invite is only valid for invited employees"
                )
            # Company name via tenant mode from DB-resolved company_id.
            await uow.enter_tenant(employee.company_id)
            company = await uow.companies.get_by_id(employee.company_id)
            return {
                "employee_id": employee.id,
                "full_name": employee.full_name,
                "email": invite.invited_email,
                "company_name": company.name if company else None,
                "expires_at": invite.expires_at,
            }

    async def accept_invite(self, *, token: str, password: str) -> Employee:
        if len(password) < 8:
            raise ValidationError("Password must be at least 8 characters")

        token_hash = hash_token(token)
        async with self._uow_factory() as uow:
            # Pin token_hash so auth RLS cannot enumerate/update other invites.
            await uow.enter_auth_bootstrap(invite_token_hash=token_hash)
            invite = await uow.employee_invites.get_by_token_hash_for_update(token_hash)
            if invite is None:
                raise NotFoundError("Invite not found")
            if invite.used_at is not None:
                raise ValidationError("Invite already used")
            if invite.expires_at < datetime.now(UTC):
                raise ValidationError("Invite expired")

            # Pin employee for subject update + sibling invite invalidate.
            await uow.enter_auth_bootstrap(employee_id=invite.employee_id)
            employee = await uow.employees.get_by_id(invite.employee_id)
            if employee is None:
                raise NotFoundError("Employee not found")
            # Only INVITED → ACTIVE via onboarding invite (blocks ACTIVE takeover).
            if employee.status != EmployeeStatus.INVITED.value:
                raise ValidationError(
                    "Invite is only valid for invited employees"
                )

            updated = await uow.employees.update(
                employee.id,
                password_hash=hash_password(password),
                status=EmployeeStatus.ACTIVE.value,
            )
            # Consume this invite and any siblings so leftover tokens cannot
            # overwrite the password after activation / resend races.
            await uow.employee_invites.invalidate_unused_for_employee(employee.id)
            # Drop any pre-existing refresh sessions for this employee only
            # (e.g. bot-issued tokens while still invited).
            await uow.enter_session_bootstrap()
            await uow.refresh_sessions.revoke_all_for_subject(
                subject_type=SUBJECT_EMPLOYEE,
                subject_id=employee.id,
            )
            await uow.commit()
            if updated is None:
                raise NotFoundError("Employee not found")
            return updated


class SubscriptionMixin:
    async def _create_subscription(
        self,
        uow: UnitOfWork,
        *,
        company_id: UUID,
        tier: str = SubscriptionTier.STARTER.value,
        status: str = SubscriptionStatus.TRIAL.value,
        super_admin_id: UUID | None = None,
    ) -> CompanySubscription:
        limits = tier_limits(tier)
        now = datetime.now(UTC)
        # P0-06: demote existing current row(s) before inserting a new current
        # so the partial unique index is never violated.
        await uow.company_subscriptions.clear_current_for_company(company_id)
        subscription = await uow.company_subscriptions.create(
            CompanySubscription(
                company_id=company_id,
                tier=tier,
                status=status,
                payment_status=PaymentStatus.UNPAID.value,
                started_at=now,
                ends_at=now + timedelta(days=_TRIAL_DAYS),
                auto_renew=True,
                employee_limit=limits["employees"],
                program_limit=limits["programs"],
                is_current=True,
            ),
        )
        await uow.subscription_history.create(
            SubscriptionHistoryEvent(
                company_id=company_id,
                subscription_id=subscription.id,
                event_type=SubscriptionHistoryEventType.CREATED.value,
                new_status=status,
                new_tier=tier,
                note="Initial subscription",
                metadata_={},
                actor_super_admin_id=super_admin_id,
            ),
        )
        return subscription

    async def _record_subscription_event(
        self,
        uow: UnitOfWork,
        *,
        subscription: CompanySubscription,
        event_type: str,
        super_admin_id: UUID | None,
        previous_status: str | None = None,
        new_status: str | None = None,
        previous_tier: str | None = None,
        new_tier: str | None = None,
        note: str | None = None,
    ) -> None:
        await uow.subscription_history.create(
            SubscriptionHistoryEvent(
                company_id=subscription.company_id,
                subscription_id=subscription.id,
                event_type=event_type,
                previous_status=previous_status,
                new_status=new_status,
                previous_tier=previous_tier,
                new_tier=new_tier,
                note=note,
                metadata_={},
                actor_super_admin_id=super_admin_id,
            ),
        )

    async def _usage_counts(self, uow: UnitOfWork, company_id: UUID) -> dict[str, int]:
        from app.db.models.assignment import Assignment
        from app.db.models.onboarding_program import OnboardingProgram

        employees = await uow.session.scalar(
            select(func.count()).select_from(Employee).where(Employee.company_id == company_id)
        )
        programs = await uow.session.scalar(
            select(func.count())
            .select_from(OnboardingProgram)
            .where(OnboardingProgram.company_id == company_id)
        )
        assignments = await uow.session.scalar(
            select(func.count())
            .select_from(Assignment)
            .where(Assignment.company_id == company_id)
        )
        return {
            "employees_count": int(employees or 0),
            "programs_count": int(programs or 0),
            "assignments_count": int(assignments or 0),
        }
