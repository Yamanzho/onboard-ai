"""Phase 9G Telegram reminder buttons and stale-send skip."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.bot.api.client import OnboardApiClient, TelegramOutboundDelivery
from app.bot.handlers.onboarding import (
    reminder_ack_callback,
    reminder_disable_callback,
    reminder_reduce_callback,
)
from app.bot.keyboards.onboarding import (
    assignment_notice_keyboard,
    parse_remind_ack_callback,
    parse_remind_disable_callback,
    parse_remind_reduce_callback,
    reminder_keyboard,
)
from app.bot.services.outbound_delivery import TelegramOutboundExecutor

pytestmark = pytest.mark.telegram


def test_reminder_keyboard_parsers() -> None:
    assignment_id = uuid4()
    markup = reminder_keyboard(assignment_id)
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert labels == [
        "Открыть",
        "Понял",
        "Напоминать реже",
        "Не напоминать больше",
    ]
    assert parse_remind_ack_callback(
        markup.inline_keyboard[1][0].callback_data
    ) == assignment_id
    assert parse_remind_reduce_callback(
        markup.inline_keyboard[2][0].callback_data
    ) == assignment_id
    assert parse_remind_disable_callback(
        markup.inline_keyboard[3][0].callback_data
    ) == assignment_id
    notice = assignment_notice_keyboard(assignment_id)
    assert notice.inline_keyboard[0][0].text == "Открыть"


def _callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user = MagicMock()
    callback.from_user.id = 42
    callback.message = MagicMock()
    callback.answer = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_ack_reduce_disable_call_api_and_do_not_open() -> None:
    assignment_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.acknowledge_assignment_reminder = AsyncMock()
    api.reduce_assignment_reminders = AsyncMock()
    api.disable_assignment_reminders = AsyncMock()
    api.get_progress = AsyncMock()

    await reminder_ack_callback(_callback(f"rack:{assignment_id}"), api)
    api.acknowledge_assignment_reminder.assert_awaited_once_with(assignment_id)
    api.get_progress.assert_not_called()

    await reminder_reduce_callback(_callback(f"rred:{assignment_id}"), api)
    api.reduce_assignment_reminders.assert_awaited_once_with(assignment_id)

    await reminder_disable_callback(_callback(f"rdis:{assignment_id}"), api)
    api.disable_assignment_reminders.assert_awaited_once_with(assignment_id)


@pytest.mark.asyncio
async def test_stale_assignment_outbound_is_not_sent() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    api = MagicMock(spec=OnboardApiClient)
    api.allow_assignment_outbound = AsyncMock(return_value=False)
    api.mark_telegram_outbound_failed = AsyncMock(return_value=True)
    api.mark_telegram_outbound_sent = AsyncMock()
    delivery = TelegramOutboundDelivery(
        state="acquired",
        message_id=uuid4(),
        owner_token=uuid4(),
        chat_id=700,
        source_type="assignment_reminder",
        source_key=f"assignment:{uuid4()}:reminder:2026-09-04:1",
        body="Напоминание",
        parse_mode="HTML",
        attempt_count=1,
        telegram_message_id=None,
    )
    await TelegramOutboundExecutor(bot, api).deliver_claimed(delivery)
    bot.send_message.assert_not_awaited()
    api.mark_telegram_outbound_failed.assert_awaited_once()
    assert (
        api.mark_telegram_outbound_failed.await_args.kwargs["error_category"]
        == "assignment_closed"
    )


@pytest.mark.asyncio
async def test_reminder_send_attaches_keyboard_when_allowed() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=55))
    api = MagicMock(spec=OnboardApiClient)
    api.allow_assignment_outbound = AsyncMock(return_value=True)
    api.mark_telegram_outbound_sent = AsyncMock(return_value=True)
    assignment_id = uuid4()
    delivery = TelegramOutboundDelivery(
        state="acquired",
        message_id=uuid4(),
        owner_token=uuid4(),
        chat_id=700,
        source_type="assignment_reminder",
        source_key=f"assignment:{assignment_id}:reminder:2026-09-04:1",
        body="Напоминание",
        parse_mode="HTML",
        attempt_count=1,
        telegram_message_id=None,
    )
    await TelegramOutboundExecutor(bot, api).deliver_claimed(delivery)
    api.allow_assignment_outbound.assert_awaited_once()
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert "Понял" in labels
    api.mark_telegram_outbound_sent.assert_awaited_once()
