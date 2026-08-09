"""Subscription entitlement checks for tenant operations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, ValidationError
from app.db.enums import SubscriptionStatus
from app.db.models.company_subscription import CompanySubscription
from app.db.uow import UnitOfWork

_ALLOWED_SUBSCRIPTION_STATUSES = frozenset(
    {
        SubscriptionStatus.TRIAL.value,
        SubscriptionStatus.ACTIVE.value,
    }
)


def subscription_grants_access(
    subscription: CompanySubscription | None,
    *,
    now: datetime,
    fail_closed_when_missing: bool,
) -> bool:
    """Return whether the current subscription grants tenant API access.

    Policy:
    - current row required (``is_current`` is resolved by the repository)
    - status in {trial, active}
    - ends_at is NULL (no expiration) OR ends_at > now (UTC-aware)
    - payment_status and auto_renew are ignored
    - status is never mutated here
    """
    if subscription is None:
        return not fail_closed_when_missing
    if subscription.status not in _ALLOWED_SUBSCRIPTION_STATUSES:
        return False
    if subscription.ends_at is not None and subscription.ends_at <= now:
        return False
    return True


async def ensure_subscription_allows_access(uow: UnitOfWork, company_id: UUID) -> None:
    """Deny tenant auth/API when the current subscription is not entitled.

    Production: missing current subscription is fail-closed.
    Development/tests: missing subscription is allowed for legacy fixtures.
    Platform-provisioned tenants always receive a subscription on create.
    """
    subscription = await uow.company_subscriptions.get_current_for_company(company_id)
    entitled = subscription_grants_access(
        subscription,
        now=datetime.now(UTC),
        fail_closed_when_missing=get_settings().is_production,
    )
    if not entitled:
        raise ForbiddenError("Company subscription is not active")


async def ensure_employee_limit(uow: UnitOfWork, company_id: UUID) -> None:
    subscription = await uow.company_subscriptions.get_current_for_company(company_id)
    if subscription is None:
        # Preserve fixture behavior when no subscription row exists.
        # Production tenant access is already denied by ensure_subscription_allows_access.
        return
    await ensure_subscription_allows_access(uow, company_id)
    count = await uow.employees.count_by_company_id(company_id)
    if count >= subscription.employee_limit:
        raise ValidationError("Employee limit reached for this company")


async def ensure_program_limit(uow: UnitOfWork, company_id: UUID) -> None:
    subscription = await uow.company_subscriptions.get_current_for_company(company_id)
    if subscription is None:
        return
    await ensure_subscription_allows_access(uow, company_id)
    count = await uow.onboarding_programs.count_by_company_id(company_id)
    if count >= subscription.program_limit:
        raise ValidationError("Program limit reached for this company")
