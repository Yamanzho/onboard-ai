"""P1-SUBSCRIPTION: entitlement policy for current company subscriptions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.exceptions import ForbiddenError
from app.core.security import create_access_token, hash_password, hash_token
from app.db.enums import (
    EmployeeRole,
    EmployeeStatus,
    PaymentStatus,
    PlatformRole,
    SubscriptionStatus,
    SubscriptionTier,
)
from app.db.models.company_subscription import CompanySubscription
from app.db.models.employee import Employee
from app.db.models.employee_invite import EmployeeInvite
from app.db.models.super_admin import SuperAdmin
from app.schemas.super_admin import InviteAcceptRequest
from app.services.platform import PlatformService
from app.services.subscription_guard import (
    ensure_subscription_allows_access,
    subscription_grants_access,
)
from tests.conftest import _uow_factory, auth_header, sa_tokens_from_response, tenant_tokens_from_response

_DEFAULT_FUTURE_ENDS = object()


async def _set_current_subscription(
    company_id,
    *,
    status: str = SubscriptionStatus.ACTIVE.value,
    ends_at: datetime | None | object = _DEFAULT_FUTURE_ENDS,
    payment_status: str = PaymentStatus.UNPAID.value,
    auto_renew: bool = True,
    is_current: bool = True,
    started_at: datetime | None = None,
) -> CompanySubscription:
    """Replace the company's current subscription with the given entitlement shape.

    Default ``ends_at`` → future date. Explicit ``None`` → no expiration.
    """
    resolved_ends_at: datetime | None
    if ends_at is _DEFAULT_FUTURE_ENDS:
        resolved_ends_at = datetime.now(UTC) + timedelta(days=14)
    else:
        resolved_ends_at = ends_at  # type: ignore[assignment]

    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.company_subscriptions.clear_current_for_company(company_id)
        sub = await uow.company_subscriptions.create(
            CompanySubscription(
                company_id=company_id,
                tier=SubscriptionTier.STARTER.value,
                status=status,
                payment_status=payment_status,
                started_at=started_at or datetime.now(UTC),
                ends_at=resolved_ends_at,
                auto_renew=auto_renew,
                employee_limit=10,
                program_limit=3,
                is_current=is_current,
            ),
        )
        await uow.commit()
        return sub


async def _add_historical_subscription(
    company_id,
    *,
    status: str,
    ends_at: datetime | None,
) -> CompanySubscription:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        sub = await uow.company_subscriptions.create(
            CompanySubscription(
                company_id=company_id,
                tier=SubscriptionTier.STARTER.value,
                status=status,
                payment_status=PaymentStatus.PAID.value,
                started_at=datetime.now(UTC) - timedelta(days=60),
                ends_at=ends_at,
                auto_renew=False,
                employee_limit=10,
                program_limit=3,
                is_current=False,
            ),
        )
        await uow.commit()
        return sub


# ---------------------------------------------------------------------------
# Pure policy / guard unit checks
# ---------------------------------------------------------------------------


def test_ends_at_equal_now_is_denied() -> None:
    now = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)
    sub = CompanySubscription(
        company_id=uuid4(),
        tier=SubscriptionTier.STARTER.value,
        status=SubscriptionStatus.ACTIVE.value,
        started_at=now - timedelta(days=1),
        ends_at=now,
        is_current=True,
    )
    assert subscription_grants_access(sub, now=now, fail_closed_when_missing=True) is False


def test_missing_subscription_production_vs_dev() -> None:
    now = datetime.now(UTC)
    assert subscription_grants_access(None, now=now, fail_closed_when_missing=True) is False
    assert subscription_grants_access(None, now=now, fail_closed_when_missing=False) is True


@pytest.mark.asyncio
async def test_no_current_subscription_denied_in_production(
    company_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    assert settings.is_production
    async with _uow_factory() as uow:
        await uow.enter_platform()
        with pytest.raises(ForbiddenError, match="subscription"):
            await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
async def test_no_current_subscription_allowed_in_development(company_a) -> None:
    settings = get_settings()
    assert not settings.is_production
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "ends_delta", "expect_allowed"),
    [
        (SubscriptionStatus.TRIAL.value, timedelta(days=7), True),
        (SubscriptionStatus.TRIAL.value, timedelta(days=-1), False),
        (SubscriptionStatus.TRIAL.value, None, True),
        (SubscriptionStatus.ACTIVE.value, timedelta(days=7), True),
        (SubscriptionStatus.ACTIVE.value, timedelta(days=-1), False),
        (SubscriptionStatus.ACTIVE.value, None, True),
        (SubscriptionStatus.EXPIRED.value, timedelta(days=7), False),
        (SubscriptionStatus.SUSPENDED.value, timedelta(days=7), False),
        (SubscriptionStatus.BLOCKED.value, timedelta(days=7), False),
    ],
)
async def test_status_and_ends_at_matrix(
    company_a,
    status: str,
    ends_delta: timedelta | None,
    expect_allowed: bool,
) -> None:
    ends_at = None if ends_delta is None else datetime.now(UTC) + ends_delta
    await _set_current_subscription(company_a.id, status=status, ends_at=ends_at)
    async with _uow_factory() as uow:
        await uow.enter_platform()
        if expect_allowed:
            await ensure_subscription_allows_access(uow, company_a.id)
        else:
            with pytest.raises(ForbiddenError, match="subscription"):
                await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
async def test_historical_active_current_expired_denied(company_a) -> None:
    await _add_historical_subscription(
        company_a.id,
        status=SubscriptionStatus.ACTIVE.value,
        ends_at=datetime.now(UTC) + timedelta(days=30),
    )
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.EXPIRED.value,
        ends_at=datetime.now(UTC) - timedelta(days=1),
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        with pytest.raises(ForbiddenError):
            await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
async def test_current_active_historical_expired_allowed(company_a) -> None:
    await _add_historical_subscription(
        company_a.id,
        status=SubscriptionStatus.EXPIRED.value,
        ends_at=datetime.now(UTC) - timedelta(days=10),
    )
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.ACTIVE.value,
        ends_at=datetime.now(UTC) + timedelta(days=30),
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
async def test_only_current_subscription_is_evaluated(company_a) -> None:
    await _add_historical_subscription(
        company_a.id,
        status=SubscriptionStatus.BLOCKED.value,
        ends_at=None,
    )
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.TRIAL.value,
        ends_at=datetime.now(UTC) + timedelta(days=3),
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("payment_status", list(PaymentStatus))
async def test_payment_status_does_not_affect_access(
    company_a,
    payment_status: PaymentStatus,
) -> None:
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.ACTIVE.value,
        ends_at=datetime.now(UTC) + timedelta(days=5),
        payment_status=payment_status.value,
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_renew", [True, False])
async def test_auto_renew_does_not_affect_access(company_a, auto_renew: bool) -> None:
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.ACTIVE.value,
        ends_at=datetime.now(UTC) - timedelta(hours=1),
        auto_renew=auto_renew,
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        with pytest.raises(ForbiddenError):
            await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
async def test_guard_does_not_auto_expire_status(company_a) -> None:
    """Access check must not mutate status (no active→expired side effect)."""
    sub = await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.ACTIVE.value,
        ends_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    async with _uow_factory() as uow:
        await uow.enter_platform()
        with pytest.raises(ForbiddenError):
            await ensure_subscription_allows_access(uow, company_a.id)
        refreshed = await uow.company_subscriptions.get_by_id(sub.id)
        assert refreshed is not None
        assert refreshed.status == SubscriptionStatus.ACTIVE.value


# ---------------------------------------------------------------------------
# Security path: past ends_at denies all tenant access; future allows
# ---------------------------------------------------------------------------


async def _assert_tenant_paths(
    api_client: AsyncClient,
    *,
    company_id,
    employee: Employee,
    password: str,
    bot_token: str,
    expect_allowed: bool,
) -> None:
    expected = 200 if expect_allowed else 403

    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee.id), "password": password},
    )
    assert login.status_code == expected, login.text

    me = await api_client.get("/api/v1/auth/me", headers=auth_header(employee))
    assert me.status_code == expected, me.text

    employees = await api_client.get(
        f"/api/v1/employees?company_id={company_id}",
        headers=auth_header(employee),
    )
    assert employees.status_code == expected, employees.text

    programs = await api_client.get(
        f"/api/v1/programs?company_id={company_id}",
        headers=auth_header(employee),
    )
    assert programs.status_code == expected, programs.text

    kb = await api_client.get(
        f"/api/v1/knowledge/articles?company_id={company_id}",
        headers=auth_header(employee),
    )
    assert kb.status_code == expected, kb.text

    bot = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers={"X-Bot-Service-Token": bot_token},
        json={
            "company_id": str(company_id),
            "telegram_user_id": employee.telegram_user_id,
        },
    )
    assert bot.status_code == expected, bot.text

    if expect_allowed:
        assert login.status_code == 200
        refresh = await api_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tenant_tokens_from_response(login)["refresh_token"]},
        )
        assert refresh.status_code == 200, refresh.text


@pytest.mark.asyncio
async def test_security_past_ends_at_denies_all_tenant_access(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "SecurityPast1!"
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employees.update(admin_a.id, password_hash=hash_password(password))
        await uow.commit()

    bot_token = "test-bot-service-token-entitlement"
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", bot_token)
    monkeypatch.setattr(settings, "bot_company_id", str(company_a.id))

    # Establish a valid subscription and capture a refresh token first.
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.ACTIVE.value,
        ends_at=datetime.now(UTC) + timedelta(days=7),
    )
    login_ok = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(admin_a.id), "password": password},
    )
    assert login_ok.status_code == 200, login_ok.text
    refresh_token = tenant_tokens_from_response(login_ok)["refresh_token"]

    # Expire entitlement without mutating status (active + past ends_at).
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.ACTIVE.value,
        ends_at=datetime.now(UTC) - timedelta(hours=1),
    )

    await _assert_tenant_paths(
        api_client,
        company_id=company_a.id,
        employee=admin_a,
        password=password,
        bot_token=bot_token,
        expect_allowed=False,
    )

    refreshed = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refreshed.status_code == 403, refreshed.text


@pytest.mark.asyncio
async def test_security_future_ends_at_allows_tenant_access(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "SecurityFuture1!"
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employees.update(admin_a.id, password_hash=hash_password(password))
        await uow.commit()

    bot_token = "test-bot-service-token-entitlement-ok"
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", bot_token)
    monkeypatch.setattr(settings, "bot_company_id", str(company_a.id))

    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.ACTIVE.value,
        ends_at=datetime.now(UTC) + timedelta(days=30),
    )

    await _assert_tenant_paths(
        api_client,
        company_id=company_a.id,
        employee=admin_a,
        password=password,
        bot_token=bot_token,
        expect_allowed=True,
    )


@pytest.mark.asyncio
async def test_super_admin_not_blocked_by_tenant_subscription_guard(
    api_client: AsyncClient,
    company_a,
) -> None:
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.BLOCKED.value,
        ends_at=datetime.now(UTC) - timedelta(days=1),
    )

    password = "SuperAdminEnt1!"
    async with _uow_factory() as uow:
        await uow.enter_platform()
        admin = await uow.super_admins.create(
            SuperAdmin(
                email=f"sa-{uuid4().hex[:8]}@example.com",
                full_name="SA Entitlement",
                password_hash=hash_password(password),
                is_active=True,
            ),
        )
        await uow.commit()
        admin_id = admin.id
        admin_email = admin.email

    login = await api_client.post(
        "/api/v1/super-admin/auth/login",
        json={"email": admin_email, "password": password},
    )
    assert login.status_code == 200, login.text
    headers = {
        "Authorization": f"Bearer {sa_tokens_from_response(login)['access_token']}",
    }

    # Also verify a forged-style SA access token path used by other tests.
    token_headers = {
        "Authorization": (
            "Bearer "
            + create_access_token(
                subject=admin_id,
                role=PlatformRole.SUPER_ADMIN.value,
                company_id=None,
            )
        )
    }

    dash = await api_client.get("/api/v1/super-admin/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text

    company = await api_client.get(
        f"/api/v1/super-admin/companies/{company_a.id}",
        headers=token_headers,
    )
    assert company.status_code == 200, company.text


@pytest.mark.asyncio
async def test_invite_accept_does_not_grant_api_when_subscription_blocked(
    api_client: AsyncClient,
    company_a,
) -> None:
    """Invite accept may activate the employee, but login/API remain denied."""
    await _set_current_subscription(
        company_a.id,
        status=SubscriptionStatus.EXPIRED.value,
        ends_at=datetime.now(UTC) - timedelta(days=1),
    )

    raw_token = f"invite-{uuid4().hex}"
    password = "InviteAccept1!"
    async with _uow_factory() as uow:
        await uow.enter_platform()
        invited = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                telegram_user_id=880099001,
                full_name="Invited Blocked Sub",
                email="invited-blocked@example.com",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.INVITED.value,
            ),
        )
        await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_a.id,
                employee_id=invited.id,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
                invited_email="invited-blocked@example.com",
            ),
        )
        await uow.commit()
        invited_id = invited.id

    service = PlatformService(uow_factory=_uow_factory)
    activated = await service.accept_invite(
        InviteAcceptRequest(token=raw_token, password=password),
    )
    assert activated.status == EmployeeStatus.ACTIVE.value
    assert activated.id == invited_id

    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(invited_id), "password": password},
    )
    assert login.status_code == 403, login.text

    me = await api_client.get(
        "/api/v1/auth/me",
        headers=auth_header(activated),
    )
    assert me.status_code == 403, me.text
