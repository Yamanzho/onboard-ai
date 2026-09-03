from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiohttp.test_utils import make_mocked_request

from app.bot.api.client import OnboardApiClient, TelegramOutboundDelivery
from app.bot.lifecycle import health_response, shutdown_bot_runtime
from app.bot.middlewares.idempotency import TelegramUpdateIdempotencyMiddleware
from app.bot.services.outbound_delivery import TelegramOutboundExecutor
from tests.bot.test_telegram_update_idempotency import _update

pytestmark = pytest.mark.telegram


def _delivery() -> TelegramOutboundDelivery:
    return TelegramOutboundDelivery(
        state="acquired",
        message_id=uuid4(),
        owner_token=uuid4(),
        chat_id=700,
        source_type="ai_chat",
        source_key="telegram-update:9001:ai-chat",
        body="Persisted payload",
        parse_mode="HTML",
        attempt_count=1,
        telegram_message_id=None,
    )


@pytest.mark.asyncio
async def test_outbound_loop_does_not_claim_after_stop() -> None:
    bot = MagicMock()
    api = MagicMock(spec=OnboardApiClient)
    api.claim_due_telegram_outbound = AsyncMock(return_value=[])
    stop = asyncio.Event()
    stop.set()
    await TelegramOutboundExecutor(bot, api).run(stop)
    api.claim_due_telegram_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbound_loop_skips_unstarted_batch_items_after_stop() -> None:
    executor = TelegramOutboundExecutor(MagicMock(), MagicMock(spec=OnboardApiClient))
    first = _delivery()
    second = _delivery()
    executor._api.claim_due_telegram_outbound = AsyncMock(return_value=[first, second])
    executor.deliver_claimed = AsyncMock()
    stop = asyncio.Event()

    async def _deliver(_delivery: TelegramOutboundDelivery) -> None:
        stop.set()

    executor.deliver_claimed.side_effect = _deliver
    await executor.run(stop)
    assert executor.deliver_claimed.await_count == 1


@pytest.mark.asyncio
async def test_cancelled_send_does_not_mark_failed() -> None:
    executor = TelegramOutboundExecutor(MagicMock(), MagicMock(spec=OnboardApiClient))
    executor._bot.send_message = AsyncMock(side_effect=asyncio.CancelledError)
    executor._api.mark_telegram_outbound_failed = AsyncMock()
    executor._api.mark_telegram_outbound_sent = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await executor.deliver_claimed(_delivery())
    executor._api.mark_telegram_outbound_failed.assert_not_awaited()
    executor._api.mark_telegram_outbound_sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotency_cancel_fails_receipt_for_reclaim() -> None:
    api = MagicMock(spec=OnboardApiClient)
    api.claim_telegram_update = AsyncMock(
        return_value=MagicMock(
            acquired=True,
            owner_token=uuid4(),
            receipt_id=uuid4(),
            state="acquired",
        )
    )
    api.bind_telegram_update = MagicMock(return_value="token")
    api.reset_telegram_update = MagicMock()
    api.fail_telegram_update = AsyncMock(return_value=True)
    middleware = TelegramUpdateIdempotencyMiddleware(api)

    async def _handler(_event: object, _data: dict) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await middleware(_handler, _update(91), {})
    api.fail_telegram_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_health_is_shallow_json() -> None:
    response = health_response(make_mocked_request("GET", "/health"))
    assert response.status == 200
    assert b'"ok"' in response.body
    assert b"redis" not in response.body.lower()
    assert b"token" not in response.body.lower()


@pytest.mark.asyncio
async def test_shutdown_helper_closes_clients_after_stop_events() -> None:
    outbound_stop = asyncio.Event()
    heartbeat_stop = asyncio.Event()
    outbound_task = asyncio.create_task(asyncio.sleep(0))
    heartbeat_task = asyncio.create_task(asyncio.sleep(0))
    api_client = MagicMock()
    api_client.aclose = AsyncMock()
    bot = MagicMock()
    bot.session.close = AsyncMock()
    bot.delete_webhook = AsyncMock()
    dispatcher = MagicMock()
    dispatcher.storage.close = AsyncMock()

    await shutdown_bot_runtime(
        outbound_stop=outbound_stop,
        heartbeat_stop=heartbeat_stop,
        outbound_task=outbound_task,
        heartbeat_task=heartbeat_task,
        dispatcher=dispatcher,
        api_client=api_client,
        bot=bot,
        delete_webhook=True,
    )
    assert outbound_stop.is_set()
    assert heartbeat_stop.is_set()
    api_client.aclose.assert_awaited()
    bot.session.close.assert_awaited()
    bot.delete_webhook.assert_awaited()
