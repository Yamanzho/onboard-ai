from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.db.uow import UnitOfWork
from app.services.telegram_outbound import TelegramOutboundService

pytestmark = [pytest.mark.api, pytest.mark.telegram]


async def _enqueue(
    employee,
    *,
    source_type: str = "ai_chat",
    source_key: str | None = None,
    body: str = "Durable reply",
):
    service = TelegramOutboundService()
    key = source_key or f"telegram-update:{uuid4().int}:ai-chat"
    async with UnitOfWork() as uow:
        await uow.enter_tenant(employee.company_id)
        row = await service.enqueue_in_uow(
            uow,
            company_id=employee.company_id,
            employee_id=employee.id,
            chat_id=employee.telegram_chat_id or employee.telegram_user_id,
            source_type=source_type,
            source_key=key,
            body=body,
        )
        await uow.commit()
    return row


@pytest.mark.asyncio
async def test_internal_delivery_contract_requires_bot_service_auth(
    api_client: AsyncClient,
    employee_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = await _enqueue(employee_a)
    path = "/api/v1/auth/bot/outbound/claim"
    request = {
        "source_type": row.source_type,
        "source_key": row.source_key,
    }
    assert (await api_client.post(path, json=request)).status_code == 401

    token = "phase-7d-unit-test-bot-service-token"
    monkeypatch.setattr(get_settings(), "bot_service_token", token)
    claimed = await api_client.post(
        path,
        headers={"X-Bot-Service-Token": token},
        json=request,
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["state"] == "acquired"
    assert claimed.json()["body"] == "Durable reply"


@pytest.mark.asyncio
async def test_enqueue_same_source_creates_exactly_one_row(employee_a) -> None:
    key = f"telegram-update:{uuid4().int}:ai-chat"
    first = await _enqueue(employee_a, source_key=key)
    second = await _enqueue(employee_a, source_key=key)

    assert second.id == first.id
    async with UnitOfWork() as uow:
        await uow.enter_tenant(employee_a.company_id)
        rows = await uow.telegram_outbound.list()
        assert sum(row.source_key == key for row in rows) == 1


@pytest.mark.asyncio
async def test_two_workers_have_one_delivery_claim_winner(employee_a) -> None:
    row = await _enqueue(employee_a)
    service = TelegramOutboundService()

    first, second = await asyncio.gather(
        service.claim_source(
            source_type=row.source_type,
            source_key=row.source_key,
        ),
        service.claim_source(
            source_type=row.source_type,
            source_key=row.source_key,
        ),
    )

    assert sum(item.state == "acquired" for item in (first, second)) == 1
    assert {first.state, second.state} == {"acquired", "sending"}


@pytest.mark.asyncio
async def test_two_skip_locked_batch_workers_claim_row_once(employee_a) -> None:
    row = await _enqueue(employee_a)
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.telegram_outbound.update(
            row.id,
            next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC),
        )
        await uow.commit()
    first, second = await asyncio.gather(
        TelegramOutboundService().claim_due_batch(limit=1),
        TelegramOutboundService().claim_due_batch(limit=1),
    )
    claimed_ids = [
        delivery.message_id
        for batch in (first, second)
        for delivery in batch
        if delivery.message_id == row.id
    ]
    assert claimed_ids == [row.id]


@pytest.mark.asyncio
async def test_transient_failure_schedules_same_payload_then_succeeds(
    employee_a,
) -> None:
    row = await _enqueue(employee_a, body="Same immutable payload")
    service = TelegramOutboundService()
    first = await service.claim_source(
        source_type=row.source_type,
        source_key=row.source_key,
    )
    assert first.owner_token is not None and first.message_id is not None
    assert await service.mark_failed(
        message_id=first.message_id,
        owner_token=first.owner_token,
        retryable=True,
        error_category="network_error",
    )

    not_due = await service.claim_source(
        source_type=row.source_type,
        source_key=row.source_key,
    )
    assert not_due.state == "pending"
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.telegram_outbound.update(
            row.id,
            next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await uow.commit()

    retry = await service.claim_source(
        source_type=row.source_type,
        source_key=row.source_key,
    )
    assert retry.state == "acquired"
    assert retry.body == first.body == "Same immutable payload"
    assert retry.owner_token is not None and retry.message_id is not None
    assert await service.mark_sent(
        message_id=retry.message_id,
        owner_token=retry.owner_token,
        telegram_message_id=987,
    )

    sent = await service.claim_source(
        source_type=row.source_type,
        source_key=row.source_key,
    )
    assert sent.state == "sent"
    assert sent.telegram_message_id == 987


@pytest.mark.asyncio
async def test_permanent_failure_is_terminal(employee_a) -> None:
    row = await _enqueue(employee_a)
    service = TelegramOutboundService()
    claim = await service.claim_source(
        source_type=row.source_type,
        source_key=row.source_key,
    )
    assert claim.owner_token is not None and claim.message_id is not None
    assert await service.mark_failed(
        message_id=claim.message_id,
        owner_token=claim.owner_token,
        retryable=False,
        error_category="forbidden",
    )

    terminal = await service.claim_source(
        source_type=row.source_type,
        source_key=row.source_key,
    )
    assert terminal.state == "failed"


@pytest.mark.asyncio
async def test_stale_sending_survives_restart_and_is_reclaimed(employee_a) -> None:
    row = await _enqueue(employee_a)
    first = await TelegramOutboundService().claim_source(
        source_type=row.source_type,
        source_key=row.source_key,
    )
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.telegram_outbound.update(
            row.id,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await uow.commit()

    restarted = await TelegramOutboundService().claim_due_batch()
    recovered = next(item for item in restarted if item.message_id == row.id)
    assert recovered.state == "acquired"
    assert recovered.owner_token != first.owner_token


@pytest.mark.asyncio
async def test_tenant_cannot_read_or_claim_another_tenant_outbox(
    employee_a,
    employee_b,
) -> None:
    row = await _enqueue(employee_a)
    async with UnitOfWork() as uow:
        await uow.enter_tenant(employee_b.company_id)
        assert (
            await uow.telegram_outbound.get_by_source(
                source_type=row.source_type,
                source_key=row.source_key,
            )
            is None
        )
        assert await uow.telegram_outbound.get_by_id(row.id) is None
