"""Phase 9I: deterministic intent routing and no-LLM small talk."""

from __future__ import annotations

import pytest

from app.db.enums import AssistantIntent
from app.services.assistant.intent_router import IntentRouter


def test_deterministic_intents() -> None:
    router = IntentRouter(llm_provider=None)
    cases = [
        ("Привет", AssistantIntent.GREETING),
        ("hello", AssistantIntent.GREETING),
        ("салам", AssistantIntent.GREETING),
        ("Спасибо", AssistantIntent.THANKS),
        ("thanks", AssistantIntent.THANKS),
        ("Что ты умеешь?", AssistantIntent.HELP),
        ("Что мне делать?", AssistantIntent.NEXT_TASK),
        ("что дальше", AssistantIntent.NEXT_TASK),
        ("мои задачи", AssistantIntent.NEXT_TASK),
        ("Какой у меня прогресс?", AssistantIntent.ASSIGNMENT_STATUS),
        ("Сколько осталось?", AssistantIntent.ASSIGNMENT_STATUS),
        ("Продолжи курс", AssistantIntent.CONTINUE_LEARNING),
        ("продолжить обучение", AssistantIntent.CONTINUE_LEARNING),
        ("Я не понял этот урок", AssistantIntent.TRAINING_HELP),
        ("Объясни это проще", AssistantIntent.TRAINING_HELP),
        ("Кто отвечает за ноутбуки?", AssistantIntent.RESPONSIBLE_TOPIC),
        ("к кому обратиться по зарплате", AssistantIntent.RESPONSIBLE_TOPIC),
        ("Как оформить отпуск?", AssistantIntent.COMPANY_KNOWLEDGE),
        ("Какие правила командировок?", AssistantIntent.COMPANY_KNOWLEDGE),
        ("Что такое испытательный срок?", AssistantIntent.COMPANY_KNOWLEDGE),
    ]
    for text, expected in cases:
        routed = router.route_deterministic(text)
        assert routed is not None, text
        assert routed.intent is expected, text
        assert routed.used_llm is False, text


def test_greeting_does_not_steal_knowledge_question() -> None:
    router = IntentRouter(llm_provider=None)
    routed = router.route_deterministic("Привет, как оформить отпуск?")
    assert routed is not None
    assert routed.intent is AssistantIntent.COMPANY_KNOWLEDGE


@pytest.mark.asyncio
async def test_unknown_falls_back_safely() -> None:
    router = IntentRouter(llm_provider=None)
    routed = await router.route("asdfgh")
    assert routed.intent is AssistantIntent.UNKNOWN
