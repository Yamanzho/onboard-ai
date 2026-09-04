"""Phase 9E: Telegram structured quiz buttons and result copy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.bot.api.client import OnboardApiClient
from app.bot.api.schemas import (
    AssignmentProgressDTO,
    ProgramDTO,
    ProgressItemDTO,
    ProgressStepDTO,
)
from app.bot.handlers.onboarding import (
    structured_quiz_confirm,
    structured_quiz_select,
    structured_quiz_text,
)
from app.bot.keyboards.onboarding import (
    parse_quiz_confirm_callback,
    parse_quiz_select_callback,
    quiz_options_keyboard,
)
from app.bot.states.onboarding import OnboardingStates
from app.services.assessment import format_quiz_result_message


def test_quiz_keyboard_single_and_multiple() -> None:
    options = [{"id": "a", "text": "Almaty"}, {"id": "b", "text": "Astana"}]
    single = quiz_options_keyboard(0, options, multiple=False)
    assert len(single.inline_keyboard) == 2
    assert single.inline_keyboard[0][0].callback_data == "qsel:0:a"
    assert parse_quiz_select_callback("qsel:0:a") == (0, "a")

    multiple = quiz_options_keyboard(1, options, multiple=True, selected={"b"})
    assert multiple.inline_keyboard[-1][0].callback_data == "qok:1"
    assert "☑" in multiple.inline_keyboard[1][0].text
    assert parse_quiz_confirm_callback("qok:1") == 1


def test_result_copy() -> None:
    assert format_quiz_result_message(score=85, passed=True).startswith(
        "Результат: 85%"
    )
    failed = format_quiz_result_message(score=70, passed=False)
    assert "70%" in failed
    assert "80%" in failed
    assert "ещё раз" in failed


def _state(data: dict) -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    return state


def _callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user = MagicMock()
    callback.from_user.id = 42
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.message.bot = MagicMock()
    callback.answer = AsyncMock()
    return callback


def _structured_item() -> ProgressItemDTO:
    return ProgressItemDTO(
        id=uuid4(),
        assignment_id=uuid4(),
        step_id=uuid4(),
        status="in_progress",
        payload={},
        step=ProgressStepDTO(
            title="Exam",
            description=None,
            step_type="quiz",
            content={
                "questions": [
                    {
                        "id": "q1",
                        "type": "single_choice",
                        "text": "Capital?",
                        "options": [
                            {"id": "a", "text": "Almaty"},
                            {"id": "b", "text": "Astana"},
                        ],
                    },
                    {
                        "id": "q2",
                        "type": "multiple_choice",
                        "text": "Even?",
                        "options": [
                            {"id": "a", "text": "2"},
                            {"id": "b", "text": "3"},
                        ],
                    },
                ]
            },
            position=0,
        ),
    )


@pytest.mark.asyncio
async def test_structured_text_is_rejected() -> None:
    message = MagicMock()
    message.answer = AsyncMock()
    await structured_quiz_text(message, AsyncMock(), AsyncMock())
    message.answer.assert_awaited_once()
    assert "кнопк" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_single_choice_select_advances() -> None:
    item = _structured_item()
    assignment_id = item.assignment_id
    program_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.get_program = AsyncMock(
        return_value=ProgramDTO(
            id=program_id,
            company_id=uuid4(),
            title="Course",
            description=None,
            is_active=True,
        )
    )
    api.get_progress = AsyncMock(
        return_value=AssignmentProgressDTO(percentage=0, items=[item])
    )
    api.first_incomplete_step = OnboardApiClient.first_incomplete_step
    api.complete_progress = AsyncMock()
    state = _state(
        {
            "assignment_id": str(assignment_id),
            "program_id": str(program_id),
            "progress_id": str(item.id),
            "telegram_user_id": 42,
            "quiz_q_index": 0,
            "quiz_answers": {},
            "quiz_toggles": [],
        }
    )
    callback = _callback("qsel:0:b")
    await structured_quiz_select(callback, api, state)
    api.complete_progress.assert_not_called()
    callback.message.edit_text.assert_awaited()
    assert "Вопрос 2" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_multiple_choice_confirm_submits_fail_feedback() -> None:
    item = _structured_item()
    item.step.content = {"questions": [item.step.content["questions"][1]]}
    assignment_id = item.assignment_id
    program_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.get_program = AsyncMock(
        return_value=ProgramDTO(
            id=program_id,
            company_id=uuid4(),
            title="Course",
            description=None,
            is_active=True,
        )
    )
    progress = AssignmentProgressDTO(percentage=0, items=[item])
    api.get_progress = AsyncMock(return_value=progress)
    api.first_incomplete_step = OnboardApiClient.first_incomplete_step
    api.complete_progress = AsyncMock(
        return_value=ProgressItemDTO(
            id=item.id,
            assignment_id=assignment_id,
            step_id=item.step_id,
            status="in_progress",
            payload={
                "attempt_count": 1,
                "last_score": 0,
                "best_score": 0,
                "passed": False,
                "quiz_score": {"score": 0, "passed": False, "passing_score": 80},
            },
            step=item.step,
        )
    )
    api.current_telegram_update_id = MagicMock(return_value=None)
    state = _state(
        {
            "assignment_id": str(assignment_id),
            "program_id": str(program_id),
            "progress_id": str(item.id),
            "telegram_user_id": 42,
            "quiz_q_index": 0,
            "quiz_answers": {},
            "quiz_toggles": ["a"],
        }
    )
    callback = _callback("qok:0")
    await structured_quiz_confirm(callback, api, state)
    api.complete_progress.assert_awaited()
    payload = api.complete_progress.await_args.kwargs["payload"]
    assert payload["answers"][0]["selected_option_ids"] == ["a"]
    callback.message.answer.assert_awaited()
    texts = [call.args[0] for call in callback.message.answer.await_args_list]
    assert any("ещё раз" in text for text in texts)


def test_onboarding_states_include_structured() -> None:
    assert OnboardingStates.answering_structured_quiz
    assert OnboardingStates.answering_quiz
