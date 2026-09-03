from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.db.uow import UnitOfWork
from app.services.idempotency import IdempotencyService

pytestmark = [pytest.mark.api, pytest.mark.telegram]


def _update_id() -> int:
    return uuid4().int % 9_000_000_000_000_000_000


@pytest.fixture
def bot_service_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "phase-7c-unit-test-bot-service-token"
    monkeypatch.setattr(get_settings(), "bot_service_token", token)
    return token


@pytest.mark.asyncio
async def test_internal_bot_update_contract_is_authenticated_and_replay_safe(
    api_client: AsyncClient,
    bot_service_token: str,
) -> None:
    update_id = _update_id()
    path = "/api/v1/auth/bot/updates/claim"
    missing = await api_client.post(
        path,
        json={"update_id": update_id, "update_type": "message"},
    )
    assert missing.status_code == 401

    headers = {"X-Bot-Service-Token": bot_service_token}
    claimed = await api_client.post(
        path,
        headers=headers,
        json={"update_id": update_id, "update_type": "message"},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["state"] == "acquired"
    assert claimed.json()["owner_token"]

    completed = await api_client.post(
        "/api/v1/auth/bot/updates/complete",
        headers=headers,
        json={
            "receipt_id": claimed.json()["receipt_id"],
            "owner_token": claimed.json()["owner_token"],
        },
    )
    assert completed.status_code == 200
    assert completed.json() == {"updated": True}

    replay = await api_client.post(
        path,
        headers=headers,
        json={"update_id": update_id, "update_type": "message"},
    )
    assert replay.status_code == 200
    assert replay.json()["state"] == "completed"
    assert replay.json()["owner_token"] is None


@pytest.mark.asyncio
async def test_completed_telegram_update_is_a_durable_duplicate() -> None:
    service = IdempotencyService()
    update_id = _update_id()

    claimed = await service.claim_telegram_update(
        update_id=update_id,
        update_type="message",
    )
    assert claimed.acquired
    assert claimed.owner_token is not None
    assert await service.complete_telegram_update(
        receipt_id=claimed.receipt_id,
        owner_token=claimed.owner_token,
    )

    duplicate = await service.claim_telegram_update(
        update_id=update_id,
        update_type="message",
    )
    assert duplicate.state == "completed"
    assert not duplicate.acquired


@pytest.mark.asyncio
async def test_concurrent_telegram_claim_has_exactly_one_winner() -> None:
    update_id = _update_id()

    async def claim():
        return await IdempotencyService().claim_telegram_update(
            update_id=update_id,
            update_type="callback_query",
        )

    first, second = await asyncio.gather(claim(), claim())
    assert sum(result.acquired for result in (first, second)) == 1
    assert {first.state, second.state} == {"acquired", "processing"}


@pytest.mark.asyncio
async def test_failed_telegram_claim_can_be_retried_immediately() -> None:
    service = IdempotencyService()
    update_id = _update_id()
    first = await service.claim_telegram_update(
        update_id=update_id,
        update_type="message",
    )
    assert first.owner_token is not None
    assert await service.fail_telegram_update(
        receipt_id=first.receipt_id,
        owner_token=first.owner_token,
    )

    retry = await service.claim_telegram_update(
        update_id=update_id,
        update_type="message",
    )
    assert retry.acquired
    assert retry.receipt_id == first.receipt_id
    assert retry.owner_token != first.owner_token


@pytest.mark.asyncio
async def test_stale_processing_claim_is_atomically_recoverable() -> None:
    service = IdempotencyService()
    update_id = _update_id()
    first = await service.claim_telegram_update(
        update_id=update_id,
        update_type="message",
    )
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.idempotency_receipts.update(
            first.receipt_id,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await uow.commit()

    retry = await service.claim_telegram_update(
        update_id=update_id,
        update_type="message",
    )
    assert retry.acquired
    assert retry.receipt_id == first.receipt_id
    assert retry.owner_token != first.owner_token
