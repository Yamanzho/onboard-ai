"""AI catch-all must not steal learning, quiz, ack, or cabinet handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.handlers import get_handlers_router
from app.bot.handlers.ai import ai_question
from app.bot.handlers.onboarding import (
    acknowledgement_view_callback,
    complete_step_callback,
    open_assignment_callback,
    quiz_answers,
)
from app.bot.handlers.start import cmd_start
from app.bot.keyboards.onboarding import (
    ACK_CONFIRM_PREFIX,
    ACK_VIEW_PREFIX,
    ASSIGN_OPEN_PREFIX,
    BLOCK_NEXT_PREFIX,
)
from app.bot.states.onboarding import OnboardingStates


@pytest.mark.asyncio
async def test_quiz_and_ack_states_are_ignored_by_ai() -> None:
    api = AsyncMock()
    message = MagicMock()
    message.text = "вариант A"
    message.from_user = MagicMock()
    message.from_user.id = 1
    message.answer = AsyncMock()
    state = AsyncMock()
    for current in (
        OnboardingStates.answering_quiz.state,
        OnboardingStates.answering_structured_quiz.state,
        OnboardingStates.viewing_step.state,
    ):
        state.get_state = AsyncMock(return_value=current)
        await ai_question(message, api, state)
        api.post_assistant_chat.assert_not_called()
        message.answer.assert_not_called()


def test_router_order_and_specific_handlers_exist() -> None:
    names = [router.name for router in get_handlers_router().sub_routers]
    assert names == ["start", "onboarding", "cabinet", "ai"]
    assert cmd_start.__module__ == "app.bot.handlers.start"
    assert quiz_answers.__module__ == "app.bot.handlers.onboarding"
    assert complete_step_callback.__module__ == "app.bot.handlers.onboarding"
    assert open_assignment_callback.__module__ == "app.bot.handlers.onboarding"
    assert acknowledgement_view_callback.__module__ == "app.bot.handlers.onboarding"
    assert ACK_VIEW_PREFIX.startswith("ack")
    assert ACK_CONFIRM_PREFIX.startswith("ack")
    assert ASSIGN_OPEN_PREFIX
    assert BLOCK_NEXT_PREFIX
