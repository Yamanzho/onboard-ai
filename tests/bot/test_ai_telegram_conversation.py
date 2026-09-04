"""AI-11C Telegram conversation pointer: reuse, /newchat, stale recovery."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.handlers.ai import ai_question, cmd_newchat
from app.bot.services.ai_client import (
    MSG_INTERNAL,
    MSG_NEW_CHAT,
    MSG_UNAUTHENTICATED,
    MSG_UNAVAILABLE,
    ask_company_knowledge,
    format_ai_reply,
)
from app.bot.services.ai_conversation import TelegramConversationStore
from app.bot.states.onboarding import OnboardingStates
from app.core.exceptions import ServiceUnavailableError
from tests.bot.test_ai_handler import _employee, _message, _state


@pytest.mark.asyncio
async def test_first_message_saves_returned_conversation_id(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    conversation_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=_employee())
    api.post_assistant_chat = AsyncMock(
        return_value={
            "answer": "Для VPN нужен клиент из IT-портала.",
            "text": "Для VPN нужен клиент из IT-портала.",
            "no_answer": False,
            "conversation_id": str(conversation_id),
            "citations": [{"source_id": "S1", "title": "VPN Access Policy"}],
        }
    )
    message = _message("Как получить доступ к VPN?")
    await ai_question(message, api, _state())
    api.post_assistant_chat.assert_awaited_once_with("Как получить доступ к VPN?")
    assert (
        await telegram_conversation_store.get_current_conversation(42) == conversation_id
    )
    sent = message.answer.await_args.args[0]
    assert str(conversation_id) not in sent
    assert "S1" not in sent.split("Источники:", 1)[1]


@pytest.mark.asyncio
async def test_second_message_reuses_stored_conversation_id(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    conversation_id = uuid4()
    await telegram_conversation_store.set_current_conversation(42, conversation_id)
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=_employee())
    api.post_assistant_chat = AsyncMock(
        return_value={
            "answer": "Напишите в IT.",
            "text": "Напишите в IT.",
            "no_answer": False,
            "conversation_id": str(conversation_id),
            "citations": [],
        }
    )
    await ai_question(_message("А кому написать?"), api, _state())
    api.post_assistant_chat.assert_awaited_once_with(
        "А кому написать?", conversation_id=conversation_id
    )


@pytest.mark.asyncio
async def test_newchat_clears_pointer_without_calling_chat(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    conversation_id = uuid4()
    await telegram_conversation_store.set_current_conversation(42, conversation_id)
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=_employee())
    api.post_ai_chat = AsyncMock()
    message = _message("/newchat")
    await cmd_newchat(message, api, _state())
    api.post_ai_chat.assert_not_called()
    message.answer.assert_awaited_once_with(MSG_NEW_CHAT)
    assert await telegram_conversation_store.get_current_conversation(42) is None


@pytest.mark.asyncio
async def test_newchat_does_not_run_during_onboarding_fsm(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    conversation_id = uuid4()
    await telegram_conversation_store.set_current_conversation(42, conversation_id)
    api = AsyncMock(spec=OnboardApiClient)
    message = _message("/newchat")
    await cmd_newchat(
        message,
        api,
        _state(current=OnboardingStates.answering_quiz.state),
    )
    api.find_employee_by_telegram.assert_not_called()
    message.answer.assert_not_called()
    assert (
        await telegram_conversation_store.get_current_conversation(42) == conversation_id
    )


@pytest.mark.asyncio
async def test_stale_404_is_not_retried_by_bot(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    stale = uuid4()
    await telegram_conversation_store.set_current_conversation(42, stale)
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock(
        side_effect=OnboardApiError(
            "API POST /api/v1/ai/chat failed (404): Conversation not found",
            status_code=404,
            detail="Conversation not found",
        )
    )
    reply = await ask_company_knowledge(
        api,
        "VPN?",
        telegram_user_id=42,
        conversations=telegram_conversation_store,
    )
    assert reply == MSG_UNAUTHENTICATED
    api.post_ai_chat.assert_awaited_once_with("VPN?", conversation_id=stale)
    assert await telegram_conversation_store.get_current_conversation(42) == stale


@pytest.mark.asyncio
async def test_archived_400_is_not_retried_by_bot(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    stale = uuid4()
    await telegram_conversation_store.set_current_conversation(42, stale)
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock(
        side_effect=OnboardApiError(
            "API POST /api/v1/ai/chat failed (400): "
            "Cannot add messages to an archived conversation",
            status_code=400,
            detail="Cannot add messages to an archived conversation",
        )
    )
    reply = await ask_company_knowledge(
        api,
        "VPN?",
        telegram_user_id=42,
        conversations=telegram_conversation_store,
    )
    assert reply == MSG_INTERNAL
    api.post_ai_chat.assert_awaited_once_with("VPN?", conversation_id=stale)
    assert await telegram_conversation_store.get_current_conversation(42) == stale


@pytest.mark.asyncio
async def test_generic_400_is_not_retried(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    stale = uuid4()
    await telegram_conversation_store.set_current_conversation(42, stale)
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock(
        side_effect=OnboardApiError(
            "API POST /api/v1/ai/chat failed (400): question must not be empty",
            status_code=400,
            detail="question must not be empty",
        )
    )
    reply = await ask_company_knowledge(
        api,
        "VPN?",
        telegram_user_id=42,
        conversations=telegram_conversation_store,
    )
    assert reply == MSG_INTERNAL
    api.post_ai_chat.assert_awaited_once()
    assert await telegram_conversation_store.get_current_conversation(42) == stale


@pytest.mark.asyncio
async def test_no_answer_still_stores_conversation_id(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    conversation_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock(
        return_value={
            "answer": "I could not find an answer in the company knowledge base.",
            "no_answer": True,
            "conversation_id": str(conversation_id),
            "citations": [],
        }
    )
    reply = await ask_company_knowledge(
        api,
        "unknown policy",
        telegram_user_id=42,
        conversations=telegram_conversation_store,
    )
    assert "I could not find an answer" in reply
    assert str(conversation_id) not in reply
    assert (
        await telegram_conversation_store.get_current_conversation(42) == conversation_id
    )


def test_format_ai_reply_hides_conversation_id() -> None:
    conversation_id = str(uuid4())
    text = format_ai_reply(
        {
            "answer": "Use the IT portal.",
            "no_answer": False,
            "conversation_id": conversation_id,
            "citations": [{"source_id": "S1", "title": "VPN Access Policy"}],
        }
    )
    assert conversation_id not in text
    assert "S1" not in text.split("Источники:", 1)[1]


@pytest.mark.asyncio
async def test_redis_unavailable_is_user_safe(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock()

    async def _boom(_telegram_user_id: int):
        raise ServiceUnavailableError("Conversation session temporarily unavailable")

    telegram_conversation_store.get_current_conversation = _boom  # type: ignore[method-assign]
    reply = await ask_company_knowledge(
        api,
        "VPN?",
        telegram_user_id=42,
        conversations=telegram_conversation_store,
    )
    assert reply == MSG_UNAVAILABLE
    api.post_ai_chat.assert_not_called()
