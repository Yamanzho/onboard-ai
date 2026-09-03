from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, Update, User

from app.bot.api.client import OnboardApiClient, TelegramUpdateClaim
from app.bot.middlewares.idempotency import TelegramUpdateIdempotencyMiddleware

pytestmark = pytest.mark.telegram


def _update(update_id: int) -> Update:
    user = User(id=42, is_bot=False, first_name="Ada")
    chat = Chat(id=42, type="private")
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=chat,
            from_user=user,
            text="How do I get VPN access?",
        ),
    )


def _claim(state: str, *, acquired: bool = False) -> TelegramUpdateClaim:
    return TelegramUpdateClaim(
        state=state,
        receipt_id=uuid4(),
        owner_token=uuid4() if acquired else None,
    )


@pytest.mark.asyncio
async def test_completed_duplicate_executes_handler_and_response_only_once() -> None:
    api = MagicMock(spec=OnboardApiClient)
    api.claim_telegram_update = AsyncMock(
        side_effect=[_claim("acquired", acquired=True), _claim("completed")]
    )
    api.complete_telegram_update = AsyncMock(return_value=True)
    api.fail_telegram_update = AsyncMock(return_value=True)
    api.bind_telegram_update = MagicMock(return_value=MagicMock())
    api.reset_telegram_update = MagicMock()
    middleware = TelegramUpdateIdempotencyMiddleware(api)
    response_attempt = AsyncMock()

    async def handler(_event, _data):
        await response_attempt()

    event = _update(1001)
    await middleware(handler, event, {})
    await middleware(handler, event, {})

    response_attempt.assert_awaited_once()
    api.complete_telegram_update.assert_awaited_once()
    api.fail_telegram_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_duplicate_has_exactly_one_processing_winner() -> None:
    api = MagicMock(spec=OnboardApiClient)
    claims = iter([_claim("acquired", acquired=True), _claim("processing")])

    async def claim_once(**_kwargs):
        return next(claims)

    api.claim_telegram_update = AsyncMock(side_effect=claim_once)
    api.complete_telegram_update = AsyncMock(return_value=True)
    api.fail_telegram_update = AsyncMock(return_value=True)
    api.bind_telegram_update = MagicMock(return_value=MagicMock())
    api.reset_telegram_update = MagicMock()
    middleware = TelegramUpdateIdempotencyMiddleware(api)
    handler = AsyncMock()
    event = _update(1002)

    await asyncio.gather(
        middleware(handler, event, {}),
        middleware(handler, event, {}),
    )

    handler.assert_awaited_once()
    api.complete_telegram_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_failure_marks_claim_retryable_and_retry_can_succeed() -> None:
    api = MagicMock(spec=OnboardApiClient)
    api.claim_telegram_update = AsyncMock(
        side_effect=[
            _claim("acquired", acquired=True),
            _claim("acquired", acquired=True),
        ]
    )
    api.complete_telegram_update = AsyncMock(return_value=True)
    api.fail_telegram_update = AsyncMock(return_value=True)
    api.bind_telegram_update = MagicMock(return_value=MagicMock())
    api.reset_telegram_update = MagicMock()
    middleware = TelegramUpdateIdempotencyMiddleware(api)
    handler = AsyncMock(side_effect=[RuntimeError("crash before completion"), None])
    event = _update(1003)

    with pytest.raises(RuntimeError, match="crash before completion"):
        await middleware(handler, event, {})
    await middleware(handler, event, {})

    assert handler.await_count == 2
    api.fail_telegram_update.assert_awaited_once()
    api.complete_telegram_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_then_completion_failure_preserves_documented_outbound_gap() -> None:
    api = MagicMock(spec=OnboardApiClient)
    api.claim_telegram_update = AsyncMock(
        side_effect=[_claim("acquired", acquired=True), _claim("processing")]
    )
    api.complete_telegram_update = AsyncMock(
        side_effect=RuntimeError("completion transport unavailable")
    )
    api.fail_telegram_update = AsyncMock(return_value=True)
    api.bind_telegram_update = MagicMock(return_value=MagicMock())
    api.reset_telegram_update = MagicMock()
    middleware = TelegramUpdateIdempotencyMiddleware(api)
    response_attempt = AsyncMock()

    async def handler(_event, _data):
        await response_attempt()

    event = _update(1004)
    with pytest.raises(RuntimeError, match="completion transport unavailable"):
        await middleware(handler, event, {})
    # An immediate Telegram retry sees the live processing lease and is suppressed.
    await middleware(handler, event, {})

    response_attempt.assert_awaited_once()
    api.fail_telegram_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_claimed_update_becomes_stable_ai_idempotency_header() -> None:
    api = OnboardApiClient(
        "http://api:8000",
        service_token="unit-test-bot-service-token",
    )
    api._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "answer": "Use the portal.",
            "no_answer": False,
            "conversation_id": str(uuid4()),
            "citations": [],
        }
    )
    token = api.bind_telegram_update(1005)
    try:
        await api.post_ai_chat("VPN?")
    finally:
        api.reset_telegram_update(token)

    assert api._post.await_args.kwargs["headers"] == {  # type: ignore[attr-defined]
        "Idempotency-Key": "telegram-update:1005:ai-chat",
        "X-Telegram-Delivery": "durable",
        "X-Bot-Service-Token": "unit-test-bot-service-token",
    }
