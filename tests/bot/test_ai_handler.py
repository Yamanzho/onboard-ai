"""AI-9C Telegram handler: catch-all after start / onboarding / cabinet."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.api.schemas import EmployeeDTO
from app.bot.handlers import get_handlers_router
from app.bot.handlers.ai import ai_question
from app.bot.handlers.onboarding import quiz_answers
from app.bot.handlers.start import cmd_start
from app.bot.keyboards.menu import MENU_ACTIVE, MENU_MY_ONBOARDING, MENU_PROFILE
from app.bot.services.ai_client import (
    MSG_FORBIDDEN,
    MSG_INTERNAL,
    MSG_RATE_LIMITED,
    MSG_TIMEOUT,
    MSG_UNAUTHENTICATED,
    MSG_UNAVAILABLE,
    MSG_VALIDATION,
    ask_company_knowledge,
    format_ai_reply,
    user_error_message,
)
from app.bot.states.onboarding import OnboardingStates
from app.core.ai_constants import MAX_CHAT_QUESTION_CHARS
from app.services.ai.chat import NO_ANSWER_MESSAGE


def _employee() -> EmployeeDTO:
    return EmployeeDTO(
        id=uuid4(),
        company_id=uuid4(),
        telegram_user_id=42,
        full_name="Ada Lovelace",
        role="employee",
        status="active",
    )


def _message(text: str, *, user_id: int = 42) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.from_user = MagicMock()
    message.from_user.id = user_id
    message.chat = MagicMock()
    message.chat.id = user_id
    message.bot = MagicMock()
    message.bot.send_chat_action = AsyncMock()
    message.answer = AsyncMock()
    return message


def _state(*, current: str | None = None) -> AsyncMock:
    state = AsyncMock()
    state.get_state = AsyncMock(return_value=current)
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_authenticated_employee_receives_answer_and_titles() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=_employee())
    api.post_ai_chat = AsyncMock(
        return_value={
            "answer": "Для VPN нужен клиент из IT-портала.",
            "no_answer": False,
            "citations": [
                {
                    "source_id": "S1",
                    "title": "VPN Access Policy",
                    "article_id": str(uuid4()),
                }
            ],
        }
    )
    message = _message("Как получить доступ к VPN?")
    await ai_question(message, api, _state())
    api.post_ai_chat.assert_awaited_once_with("Как получить доступ к VPN?")
    sent = message.answer.await_args.args[0]
    assert "Для VPN нужен клиент из IT-портала." in sent
    assert "Источники:" in sent
    assert "• VPN Access Policy" in sent
    assert "S1" not in sent.split("Источники:", 1)[1]


@pytest.mark.asyncio
async def test_unauthenticated_telegram_user_cannot_access_ai() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=None)
    api.post_ai_chat = AsyncMock()
    message = _message("Как получить VPN?")
    await ai_question(message, api, _state())
    api.post_ai_chat.assert_not_called()
    message.answer.assert_awaited_once_with(MSG_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_onboarding_fsm_state_is_not_consumed_by_ai() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    message = _message("ответ на квиз")
    await ai_question(
        message,
        api,
        _state(current=OnboardingStates.answering_quiz.state),
    )
    api.find_employee_by_telegram.assert_not_called()
    api.post_ai_chat.assert_not_called()
    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_start_command_is_not_handled_by_ai() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    message = _message("/start")
    await ai_question(message, api, _state())
    api.post_ai_chat.assert_not_called()
    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_cabinet_commands_are_not_handled_by_ai() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    for text in (MENU_ACTIVE, MENU_MY_ONBOARDING, MENU_PROFILE):
        message = _message(text)
        await ai_question(message, api, _state())
        message.answer.assert_not_called()
    api.post_ai_chat.assert_not_called()


def test_handler_priority_is_start_onboarding_cabinet_ai() -> None:
    names = [router.name for router in get_handlers_router().sub_routers]
    assert names == ["start", "onboarding", "cabinet", "ai"]
    assert cmd_start.__module__ == "app.bot.handlers.start"
    assert quiz_answers.__module__ == "app.bot.handlers.onboarding"
    assert ai_question.__module__ == "app.bot.handlers.ai"


def test_no_answer_is_rendered_from_api_payload() -> None:
    text = format_ai_reply(
        {"answer": NO_ANSWER_MESSAGE, "no_answer": True, "citations": []}
    )
    assert text == NO_ANSWER_MESSAGE
    assert "Источники:" not in text


def test_citations_use_titles_not_internal_ids() -> None:
    article_id = str(uuid4())
    text = format_ai_reply(
        {
            "answer": "Use the IT portal.",
            "no_answer": False,
            "citations": [
                {
                    "source_id": "S1",
                    "title": "VPN Access Policy",
                    "article_id": article_id,
                    "version_id": str(uuid4()),
                    "chunk_index": 3,
                    "score": 0.91,
                }
            ],
        }
    )
    assert "• VPN Access Policy" in text
    assert "Источники:" in text
    assert article_id not in text
    assert "version_id" not in text
    assert "chunk_index" not in text
    assert "0.91" not in text
    assert "S1" not in text.split("Источники:", 1)[1]


@pytest.mark.asyncio
async def test_status_errors_are_mapped_without_upstream_body() -> None:
    secret = "sk-live-openai-secret-key-do-not-leak"
    cases = (
        (401, MSG_UNAUTHENTICATED, None),
        (403, MSG_FORBIDDEN, None),
        (429, "Слишком много вопросов. Попробуйте через 60 сек.", 60),
        (429, MSG_RATE_LIMITED, None),
        (503, MSG_UNAVAILABLE, None),
        (500, MSG_INTERNAL, None),
    )
    for status, expected, retry_after in cases:
        api = AsyncMock(spec=OnboardApiClient)
        api.post_ai_chat = AsyncMock(
            side_effect=OnboardApiError(
                f"API POST /api/v1/ai/chat failed ({status}): {secret}",
                status_code=status,
                retry_after=retry_after,
            )
        )
        reply = await ask_company_knowledge(api, "VPN?")
        assert reply == expected
        assert secret not in reply
        assert "Traceback" not in reply
        assert "openai" not in reply.lower()


@pytest.mark.asyncio
async def test_timeout_is_a_short_user_message() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    reply = await ask_company_knowledge(api, "VPN?")
    assert reply == MSG_TIMEOUT
    assert "timed out" not in reply


@pytest.mark.asyncio
async def test_empty_and_overlong_messages_do_not_call_api() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=_employee())
    api.post_ai_chat = AsyncMock()
    empty = _message("   ")
    await ai_question(empty, api, _state())
    empty.answer.assert_awaited_once()
    api.post_ai_chat.assert_not_called()

    long_msg = _message("x" * (MAX_CHAT_QUESTION_CHARS + 1))
    await ai_question(long_msg, api, _state())
    assert long_msg.answer.await_args.args[0] == MSG_VALIDATION
    api.post_ai_chat.assert_not_called()


def test_user_error_message_never_echoes_exception() -> None:
    secret = "sk-proj-leaked-key"
    exc = OnboardApiError(
        f"API POST /api/v1/ai/chat failed (500): {secret} SELECT * FROM employees",
        status_code=500,
        request_id="req-internal-correlation",
    )
    text = user_error_message(exc)
    assert text == MSG_INTERNAL
    assert secret not in text
    assert "SELECT" not in text
    assert "employees" not in text
    assert "req-internal-correlation" not in text


@pytest.mark.asyncio
async def test_api_503_and_request_id_stay_off_the_user() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.post_ai_chat = AsyncMock(
        side_effect=OnboardApiError(
            "API POST /api/v1/ai/chat failed (503): sk-live-openai-secret",
            status_code=503,
            request_id="req-should-not-be-shown",
        )
    )
    reply = await ask_company_knowledge(api, "VPN?")
    assert reply == MSG_UNAVAILABLE
    assert "sk-live-openai-secret" not in reply
    assert "req-should-not-be-shown" not in reply
