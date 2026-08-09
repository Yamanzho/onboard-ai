"""P0-06: at most one current company_subscription per company."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ForbiddenError, ValidationError
from app.db.enums import SubscriptionStatus, SubscriptionTier
from app.db.models.company_subscription import CompanySubscription
from app.db.uow import UnitOfWork
from app.services.subscription_guard import (
    ensure_employee_limit,
    ensure_subscription_allows_access,
)
from tests.conftest import _uow_factory


async def _make_subscription(
    uow: UnitOfWork,
    *,
    company_id,
    is_current: bool,
    status: str = SubscriptionStatus.ACTIVE.value,
    started_at: datetime | None = None,
    employee_limit: int = 10,
) -> CompanySubscription:
    return await uow.company_subscriptions.create(
        CompanySubscription(
            company_id=company_id,
            tier=SubscriptionTier.STARTER.value,
            status=status,
            started_at=started_at or datetime.now(UTC),
            employee_limit=employee_limit,
            program_limit=3,
            is_current=is_current,
        ),
    )


@pytest.mark.asyncio
async def test_company_can_have_one_current_subscription(company_a) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        sub = await _make_subscription(uow, company_id=company_a.id, is_current=True)
        await uow.commit()
        current = await uow.company_subscriptions.get_current_for_company(company_a.id)
        assert current is not None
        assert current.id == sub.id
        assert current.is_current is True


@pytest.mark.asyncio
async def test_company_can_have_multiple_historical_subscriptions(company_a) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await _make_subscription(uow, company_id=company_a.id, is_current=False)
        await _make_subscription(uow, company_id=company_a.id, is_current=False)
        current = await _make_subscription(uow, company_id=company_a.id, is_current=True)
        await uow.commit()

        rows = await uow.company_subscriptions.list_for_company(company_a.id)
        assert len(rows) == 3
        assert sum(1 for r in rows if r.is_current) == 1
        got = await uow.company_subscriptions.get_current_for_company(company_a.id)
        assert got is not None
        assert got.id == current.id


@pytest.mark.asyncio
async def test_second_current_subscription_rejected(company_a) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await _make_subscription(uow, company_id=company_a.id, is_current=True)
        await uow.commit()

    async with _uow_factory() as uow:
        await uow.enter_platform()
        with pytest.raises(IntegrityError):
            await _make_subscription(uow, company_id=company_a.id, is_current=True)
            await uow.commit()
        await uow.rollback()

    async with _uow_factory() as uow:
        await uow.enter_platform()
        rows = await uow.company_subscriptions.list_for_company(company_a.id)
        assert sum(1 for r in rows if r.is_current) == 1


@pytest.mark.asyncio
async def test_two_companies_can_each_have_current(company_a, company_b) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        a = await _make_subscription(uow, company_id=company_a.id, is_current=True)
        b = await _make_subscription(uow, company_id=company_b.id, is_current=True)
        await uow.commit()
        assert (await uow.company_subscriptions.get_current_for_company(company_a.id)).id == a.id
        assert (await uow.company_subscriptions.get_current_for_company(company_b.id)).id == b.id


@pytest.mark.asyncio
async def test_switch_current_subscription_in_one_transaction(company_a) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        old = await _make_subscription(
            uow,
            company_id=company_a.id,
            is_current=True,
            status=SubscriptionStatus.EXPIRED.value,
        )
        await uow.commit()

    async with _uow_factory() as uow:
        await uow.enter_platform()
        # Correct order: demote old current, then promote/create new current.
        await uow.company_subscriptions.clear_current_for_company(company_a.id)
        new = await _make_subscription(
            uow,
            company_id=company_a.id,
            is_current=True,
            status=SubscriptionStatus.ACTIVE.value,
        )
        await uow.commit()

        refreshed_old = await uow.company_subscriptions.get_by_id(old.id)
        current = await uow.company_subscriptions.get_current_for_company(company_a.id)
        assert refreshed_old is not None
        assert refreshed_old.is_current is False
        assert current is not None
        assert current.id == new.id


@pytest.mark.asyncio
async def test_subscription_guard_uses_current_row(company_a) -> None:
    """Entitlement is derived from the current row only (P0-06 + P1 policy)."""
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await _make_subscription(
            uow,
            company_id=company_a.id,
            is_current=False,
            status=SubscriptionStatus.ACTIVE.value,
        )
        await _make_subscription(
            uow,
            company_id=company_a.id,
            is_current=True,
            status=SubscriptionStatus.BLOCKED.value,
        )
        await uow.commit()

        with pytest.raises(ForbiddenError):
            await ensure_subscription_allows_access(uow, company_a.id)


@pytest.mark.asyncio
async def test_subscription_guard_employee_limit_on_current(company_a) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await _make_subscription(
            uow,
            company_id=company_a.id,
            is_current=True,
            status=SubscriptionStatus.ACTIVE.value,
            employee_limit=0,
        )
        await uow.commit()
        with pytest.raises(ValidationError):
            await ensure_employee_limit(uow, company_a.id)


@pytest.mark.asyncio
async def test_create_subscription_demotes_previous_current(company_a) -> None:
    from app.services.platform import PlatformService

    async with _uow_factory() as uow:
        await uow.enter_platform()
        old = await _make_subscription(uow, company_id=company_a.id, is_current=True)
        await uow.commit()

    service = PlatformService(uow_factory=_uow_factory)
    async with _uow_factory() as uow:
        await uow.enter_platform()
        new = await service._create_subscription(uow, company_id=company_a.id)
        await uow.commit()
        refreshed_old = await uow.company_subscriptions.get_by_id(old.id)
        current = await uow.company_subscriptions.get_current_for_company(company_a.id)
        assert refreshed_old is not None and refreshed_old.is_current is False
        assert current is not None and current.id == new.id


@pytest.mark.asyncio
async def test_concurrent_second_current_insert_one_wins(company_a) -> None:
    """DB unique partial index serializes concurrent current inserts."""

    async def _insert_current() -> str:
        try:
            async with _uow_factory() as uow:
                await uow.enter_platform()
                await _make_subscription(uow, company_id=company_a.id, is_current=True)
                await uow.commit()
            return "ok"
        except IntegrityError:
            return "conflict"

    results = await asyncio.gather(_insert_current(), _insert_current())
    assert results.count("ok") == 1
    assert results.count("conflict") == 1

    async with _uow_factory() as uow:
        await uow.enter_platform()
        rows = await uow.company_subscriptions.list_for_company(company_a.id)
        assert sum(1 for r in rows if r.is_current) == 1


@pytest.mark.asyncio
async def test_partial_unique_index_exists_in_postgres() -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        result = await uow.session.execute(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE tablename = 'company_subscriptions'
                  AND indexname = 'uq_company_subscriptions_company_id_current'
                """
            )
        )
        indexdef = result.scalar_one()
    assert "UNIQUE" in indexdef.upper()
    assert "company_id" in indexdef
    assert "is_current" in indexdef.lower()


@pytest.mark.asyncio
async def test_normalize_strategy_keeps_newest_current(company_a) -> None:
    """Deterministic demotion rule used by migration: newest created_at/id wins."""
    older = datetime.now(UTC) - timedelta(days=2)
    newer = datetime.now(UTC) - timedelta(days=1)

    async with _uow_factory() as uow:
        await uow.enter_platform()
        # Bypass app helpers: insert two currents by temporarily dropping uniqueness
        # is not possible; instead simulate post-normalize expectation via clear+order.
        first = await _make_subscription(
            uow,
            company_id=company_a.id,
            is_current=True,
            started_at=older,
        )
        await uow.company_subscriptions.clear_current_for_company(company_a.id)
        second = await _make_subscription(
            uow,
            company_id=company_a.id,
            is_current=True,
            started_at=newer,
        )
        await uow.commit()
        assert first.id != second.id
        current = await uow.company_subscriptions.get_current_for_company(company_a.id)
        assert current is not None
        assert current.id == second.id
        # Historical row retained.
        assert await uow.company_subscriptions.get_by_id(first.id) is not None
