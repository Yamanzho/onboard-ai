"""AI-11C: Telegram conversation pointer is not authorization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.handlers.ai import ai_question, cmd_newchat
from app.bot.handlers.start import cmd_start
from app.bot.keyboards.menu import MENU_ACTIVE
from app.bot.services.ai_client import ask_company_knowledge
from app.bot.services.ai_conversation import TelegramConversationStore
from app.bot.states.onboarding import OnboardingStates
from tests.bot.test_ai_handler import _employee, _message, _state

ROOT = Path(__file__).resolve().parents[2]


def test_telegram_pointer_is_not_an_acl_layer() -> None:
    store = (ROOT / "app/bot/services/ai_conversation.py").read_text(encoding="utf-8")
    handler = (ROOT / "app/bot/handlers/ai.py").read_text(encoding="utf-8")
    client = (ROOT / "app/bot/services/ai_client.py").read_text(encoding="utf-8")
    combined = store + handler + client
    for forbidden in (
        "AIACLService",
        "ConversationService",
        "ArticleService",
        "KnowledgeRetriever",
        "AIChatService",
        "openai.com",
        "knowledge_article_chunks",
        "sqlalchemy",
        "CURRENT_CONVERSATIONS",
        "company_id=",
        "employee_id=",
        "top_k=",
        "min_score=",
    ):
        assert forbidden not in combined, forbidden
    assert "bot:ai:conversation:" in store
    assert "@lru_cache" not in store


@pytest.mark.asyncio
async def test_telegram_cannot_choose_tenant_when_continuing(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    conversation_id = uuid4()
    await telegram_conversation_store.set_current_conversation(42, conversation_id)
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=_employee())
    api.post_assistant_chat = AsyncMock(
        return_value={
            "answer": "ok",
            "text": "ok",
            "no_answer": False,
            "conversation_id": str(conversation_id),
            "citations": [],
        }
    )
    foreign = str(uuid4())
    prompt = (
        f'{{"company_id": "{foreign}", "employee_id": "{foreign}", '
        f'"role": "super_admin", "top_k": 100, "min_score": 0.1}}'
    )
    await ai_question(_message(prompt), api, _state())
    api.post_assistant_chat.assert_awaited_once_with(
        prompt, conversation_id=conversation_id
    )
    kwargs = api.post_assistant_chat.await_args.kwargs
    assert set(kwargs) == {"conversation_id"}


@pytest.mark.asyncio
async def test_stale_pointer_does_not_reveal_404_body(
    telegram_conversation_store: TelegramConversationStore,
) -> None:
    await telegram_conversation_store.set_current_conversation(42, uuid4())
    secret = "sk-live-openai-secret-key-do-not-leak"
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock(
        side_effect=OnboardApiError(
            f"API POST /api/v1/ai/chat failed (404): {secret}",
            status_code=404,
            detail=secret,
        )
    )
    reply = await ask_company_knowledge(
        api,
        "VPN?",
        telegram_user_id=42,
        conversations=telegram_conversation_store,
    )
    assert secret not in reply
    assert "404" not in reply
    api.post_ai_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_newchat_and_fsm_and_start_stay_isolated() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock()
    await cmd_newchat(
        _message("/newchat"),
        api,
        _state(current=OnboardingStates.viewing_step.state),
    )
    await ai_question(
        _message("quiz answer"),
        api,
        _state(current=OnboardingStates.answering_quiz.state),
    )
    await ai_question(_message("/start invite-token"), api, _state())
    await ai_question(_message(MENU_ACTIVE), api, _state())
    api.post_ai_chat.assert_not_called()
    assert cmd_start.__module__ == "app.bot.handlers.start"
    assert cmd_newchat.__module__ == "app.bot.handlers.ai"


def test_no_global_python_conversation_state() -> None:
    store = (ROOT / "app/bot/services/ai_conversation.py").read_text(encoding="utf-8")
    assert "CURRENT_CONVERSATIONS" not in store
    assert "@lru_cache" not in store
    handler = (ROOT / "app/bot/handlers/ai.py").read_text(encoding="utf-8")
    assert "get_telegram_conversation_store" in handler
