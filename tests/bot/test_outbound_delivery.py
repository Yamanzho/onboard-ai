from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from app.bot.api.client import OnboardApiClient, TelegramOutboundDelivery
from app.bot.services.outbound_delivery import (
    TelegramOutboundExecutor,
    classify_telegram_failure,
)


def _delivery(*, state: str = "acquired") -> TelegramOutboundDelivery:
    return TelegramOutboundDelivery(
        state=state,
        message_id=uuid4(),
        owner_token=uuid4() if state == "acquired" else None,
        chat_id=700,
        source_type="ai_chat",
        source_key="telegram-update:9001:ai-chat",
        body="Persisted payload",
        parse_mode="HTML",
        attempt_count=1,
        telegram_message_id=None,
    )


def _executor():
    bot = MagicMock(spec=Bot)
    api = MagicMock(spec=OnboardApiClient)
    api.mark_telegram_outbound_sent = AsyncMock(return_value=True)
    api.mark_telegram_outbound_failed = AsyncMock(return_value=True)
    return TelegramOutboundExecutor(bot, api), bot, api


@pytest.mark.asyncio
async def test_successful_delivery_persists_telegram_message_id() -> None:
    executor, bot, api = _executor()
    sent = MagicMock(message_id=321)
    bot.send_message = AsyncMock(return_value=sent)
    delivery = _delivery()

    await executor.deliver_claimed(delivery)

    bot.send_message.assert_awaited_once_with(
        chat_id=700,
        text="Persisted payload",
        parse_mode="HTML",
    )
    api.mark_telegram_outbound_sent.assert_awaited_once_with(
        message_id=delivery.message_id,
        owner_token=delivery.owner_token,
        telegram_message_id=321,
    )


@pytest.mark.asyncio
async def test_transient_failure_schedules_retry_without_changing_payload() -> None:
    executor, bot, api = _executor()
    bot.send_message = AsyncMock(side_effect=TimeoutError)
    delivery = _delivery()

    await executor.deliver_claimed(delivery)

    api.mark_telegram_outbound_failed.assert_awaited_once_with(
        message_id=delivery.message_id,
        owner_token=delivery.owner_token,
        retryable=True,
        error_category="network_error",
        retry_after_seconds=None,
    )
    assert bot.send_message.await_args.kwargs["text"] == "Persisted payload"
    api.mark_telegram_outbound_sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_permanent_failure_is_not_retried() -> None:
    executor, bot, api = _executor()
    error = TelegramForbiddenError(
        method=SendMessage(chat_id=700, text="Persisted payload"),
        message="bot was blocked",
    )
    bot.send_message = AsyncMock(side_effect=error)
    delivery = _delivery()

    await executor.deliver_claimed(delivery)

    api.mark_telegram_outbound_failed.assert_awaited_once_with(
        message_id=delivery.message_id,
        owner_token=delivery.owner_token,
        retryable=False,
        error_category="forbidden",
        retry_after_seconds=None,
    )


@pytest.mark.asyncio
async def test_two_immediate_executors_only_send_acquired_claim() -> None:
    executor, bot, api = _executor()
    acquired = _delivery()
    api.claim_telegram_outbound = AsyncMock(
        side_effect=[acquired, _delivery(state="sending")]
    )
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))

    await asyncio.gather(
        executor.deliver_source(
            source_type="ai_chat",
            source_key=acquired.source_key or "",
        ),
        executor.deliver_source(
            source_type="ai_chat",
            source_key=acquired.source_key or "",
        ),
    )

    bot.send_message.assert_awaited_once()


def test_retry_after_is_retryable_and_preserved() -> None:
    failure = classify_telegram_failure(
        TelegramRetryAfter(
            method=SendMessage(chat_id=700, text="Payload"),
            message="flood control",
            retry_after=17,
        )
    )
    assert failure.retryable
    assert failure.category == "rate_limited"
    assert failure.retry_after_seconds == 17
