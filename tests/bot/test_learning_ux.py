"""Phase 9F: Telegram block navigation, resume, stale callbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.bot.api.client import OnboardApiClient
from app.bot.api.schemas import (
    AssignmentDTO,
    AssignmentProgressDTO,
    EmployeeDTO,
    ProgramDTO,
    ProgressItemDTO,
    ProgressStepDTO,
)
from app.bot.handlers.cabinet import active_assignments
from app.bot.handlers.onboarding import (
    content_block_next,
    content_block_read,
    my_onboarding,
    open_assignment_callback,
)
from app.bot.handlers.step_content import format_block_message
from app.bot.keyboards.menu import MENU_MY_ONBOARDING
from app.bot.keyboards.onboarding import (
    content_block_keyboard,
    parse_block_next_callback,
    parse_block_read_callback,
)

pytestmark = pytest.mark.telegram


def test_block_keyboard_and_parsers() -> None:
    progress_id = uuid4()
    nxt = content_block_keyboard(progress_id, block_index=1, is_final=False)
    assert nxt.inline_keyboard[0][0].text == "Далее"
    assert parse_block_next_callback(nxt.inline_keyboard[0][0].callback_data) == (
        progress_id,
        1,
    )
    last = content_block_keyboard(progress_id, block_index=2, is_final=True)
    assert last.inline_keyboard[0][0].text == "Прочитал"
    assert parse_block_read_callback(last.inline_keyboard[0][0].callback_data) == (
        progress_id,
        2,
    )


def test_format_block_message_is_one_block() -> None:
    text = format_block_message(
        program_title="Security",
        step_number=2,
        total_steps=4,
        step_title="Passwords",
        block_text="Use long passwords.",
        block_index=1,
        block_count=5,
    )
    assert "Курс: Security" in text
    assert "Обучение 2/4: Passwords" in text
    assert "Use long passwords." in text
    assert "Прогресс: 2/5" in text


def _state(data: dict | None = None) -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=data or {})
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


def _callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user = MagicMock()
    callback.from_user.id = 42
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.message.from_user = callback.from_user
    callback.answer = AsyncMock()
    return callback


def _content_item(*, block_index: int = 0, status: str = "in_progress") -> ProgressItemDTO:
    return ProgressItemDTO(
        id=uuid4(),
        assignment_id=uuid4(),
        step_id=uuid4(),
        status=status,
        payload={"block_index": block_index, "content_started": True},
        block_index=block_index,
        step=ProgressStepDTO(
            title="Passwords",
            step_type="content",
            content={
                "blocks": [
                    {"id": "b1", "type": "text", "text": "One"},
                    {"id": "b2", "type": "text", "text": "Two"},
                    {"id": "b3", "type": "text", "text": "Three"},
                ]
            },
            content_blocks=[
                {"id": "b1", "type": "text", "text": "One"},
                {"id": "b2", "type": "text", "text": "Two"},
                {"id": "b3", "type": "text", "text": "Three"},
            ],
            block_count=3,
            position=0,
        ),
    )


@pytest.mark.asyncio
async def test_next_callback_persists_then_renders() -> None:
    item = _content_item(block_index=0)
    advanced = ProgressItemDTO(
        id=item.id,
        assignment_id=item.assignment_id,
        step_id=item.step_id,
        status="in_progress",
        payload={"block_index": 1, "content_started": True},
        block_index=1,
        step=item.step,
    )
    later = _content_item(block_index=1)
    later.id = item.id
    later.assignment_id = item.assignment_id
    program_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.advance_progress = AsyncMock(return_value=advanced)
    api.get_progress = AsyncMock(
        return_value=AssignmentProgressDTO(
            percentage=0,
            items=[later],
            program_id=program_id,
            assignment_status="in_progress",
        )
    )
    api.get_program = AsyncMock(
        return_value=ProgramDTO(
            id=program_id,
            company_id=uuid4(),
            title="Security",
            is_active=True,
        )
    )
    api.start_progress = AsyncMock(return_value=later)
    api.first_incomplete_step = OnboardApiClient.first_incomplete_step
    callback = _callback(f"pnext:{item.id}:0")
    await content_block_next(callback, api, _state())
    api.advance_progress.assert_awaited_once()
    assert api.advance_progress.await_args.kwargs["expected_block_index"] == 0
    callback.message.edit_text.assert_awaited()
    rendered = callback.message.edit_text.await_args.args[0]
    assert "Two" in rendered


@pytest.mark.asyncio
async def test_stale_next_does_not_skip() -> None:
    item = _content_item(block_index=1)
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.advance_progress = AsyncMock(return_value=item)
    program_id = uuid4()
    api.get_progress = AsyncMock(
        return_value=AssignmentProgressDTO(
            percentage=0,
            items=[item],
            program_id=program_id,
            assignment_status="in_progress",
        )
    )
    api.get_program = AsyncMock(
        return_value=ProgramDTO(
            id=program_id, company_id=uuid4(), title="Security", is_active=True
        )
    )
    api.start_progress = AsyncMock(return_value=item)
    api.first_incomplete_step = OnboardApiClient.first_incomplete_step
    callback = _callback(f"pnext:{item.id}:0")
    await content_block_next(callback, api, _state())
    api.advance_progress.assert_awaited_once()
    rendered = callback.message.edit_text.await_args.args[0]
    assert "Two" in rendered


@pytest.mark.asyncio
async def test_final_read_transitions() -> None:
    item = _content_item(block_index=2)
    completed = ProgressItemDTO(
        id=item.id,
        assignment_id=item.assignment_id,
        step_id=item.step_id,
        status="completed",
        payload={"block_index": 2},
        block_index=2,
        step=item.step,
    )
    program_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.read_progress = AsyncMock(return_value=completed)
    api.get_progress = AsyncMock(
        return_value=AssignmentProgressDTO(
            percentage=100,
            items=[completed],
            program_id=program_id,
            assignment_status="completed",
        )
    )
    api.get_program = AsyncMock(
        return_value=ProgramDTO(
            id=program_id, company_id=uuid4(), title="Security", is_active=True
        )
    )
    api.first_incomplete_step = OnboardApiClient.first_incomplete_step
    callback = _callback(f"pread:{item.id}:2")
    await content_block_read(callback, api, _state())
    api.read_progress.assert_awaited_once()
    rendered = callback.message.edit_text.await_args.args[0]
    assert "завершён" in rendered


@pytest.mark.asyncio
async def test_resume_after_fsm_clear_uses_block_index() -> None:
    item = _content_item(block_index=2)
    assignment = AssignmentDTO(
        id=item.assignment_id,
        company_id=uuid4(),
        employee_id=uuid4(),
        program_id=uuid4(),
        status="in_progress",
        assigned_at=datetime.now(UTC),
        priority="normal",
    )
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(
        return_value=EmployeeDTO(
            id=assignment.employee_id,
            company_id=assignment.company_id,
            telegram_user_id=42,
            full_name="Ada",
            role="employee",
            status="active",
        )
    )
    api.list_active_assignments = AsyncMock(return_value=[assignment])
    api.get_program = AsyncMock(
        return_value=ProgramDTO(
            id=assignment.program_id,
            company_id=assignment.company_id,
            title="Security",
            is_active=True,
        )
    )
    api.get_progress = AsyncMock(
        return_value=AssignmentProgressDTO(
            percentage=10,
            items=[item],
            program_id=assignment.program_id,
            assignment_status="in_progress",
        )
    )
    api.start_progress = AsyncMock(return_value=item)
    api.first_incomplete_step = OnboardApiClient.first_incomplete_step
    message = MagicMock()
    message.text = MENU_MY_ONBOARDING
    message.from_user = MagicMock()
    message.from_user.id = 42
    message.chat = MagicMock()
    message.chat.id = 42
    message.answer = AsyncMock()
    await my_onboarding(message, api, _state())
    texts = [call.args[0] for call in message.answer.await_args_list]
    assert any("Three" in text for text in texts)


@pytest.mark.asyncio
async def test_multiple_assignments_require_choice() -> None:
    first = AssignmentDTO(
        id=uuid4(),
        company_id=uuid4(),
        employee_id=uuid4(),
        program_id=uuid4(),
        status="in_progress",
        assigned_at=datetime.now(UTC),
        priority="critical",
    )
    second = AssignmentDTO(
        id=uuid4(),
        company_id=first.company_id,
        employee_id=first.employee_id,
        program_id=uuid4(),
        status="pending",
        assigned_at=datetime.now(UTC),
        priority="normal",
    )
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(
        return_value=EmployeeDTO(
            id=first.employee_id,
            company_id=first.company_id,
            telegram_user_id=42,
            full_name="Ada",
            role="employee",
            status="active",
        )
    )
    api.list_active_assignments = AsyncMock(return_value=[first, second])
    api.get_program = AsyncMock(
        side_effect=lambda program_id: ProgramDTO(
            id=program_id,
            company_id=first.company_id,
            title=f"P-{program_id}",
            is_active=True,
        )
    )
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 42
    message.chat = MagicMock()
    message.chat.id = 42
    message.answer = AsyncMock()
    await my_onboarding(message, api, _state())
    sent = message.answer.await_args
    assert "несколько" in sent.args[0]
    assert sent.kwargs["reply_markup"] is not None
    api.get_progress.assert_not_called()


@pytest.mark.asyncio
async def test_open_assignment_callback_resumes() -> None:
    item = _content_item(block_index=2)
    program_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.get_progress = AsyncMock(
        return_value=AssignmentProgressDTO(
            percentage=10,
            items=[item],
            program_id=program_id,
            assignment_status="in_progress",
        )
    )
    api.get_program = AsyncMock(
        return_value=ProgramDTO(
            id=program_id, company_id=uuid4(), title="Security", is_active=True
        )
    )
    api.start_progress = AsyncMock(return_value=item)
    api.first_incomplete_step = OnboardApiClient.first_incomplete_step
    callback = _callback(f"aopen:{item.assignment_id}")
    await open_assignment_callback(callback, api, _state())
    rendered = callback.message.edit_text.await_args.args[0]
    assert "Three" in rendered


@pytest.mark.asyncio
async def test_cabinet_active_has_open_buttons() -> None:
    assignment = AssignmentDTO(
        id=uuid4(),
        company_id=uuid4(),
        employee_id=uuid4(),
        program_id=uuid4(),
        status="pending",
        assigned_at=datetime.now(UTC),
        priority="important",
    )
    api = MagicMock()
    api.find_employee_by_telegram = AsyncMock(
        return_value=EmployeeDTO(
            id=assignment.employee_id,
            company_id=assignment.company_id,
            telegram_user_id=42,
            full_name="Ada",
            role="employee",
            status="active",
        )
    )
    api.list_assignments = AsyncMock(
        side_effect=lambda _eid, status=None: {
            "in_progress": [],
            "pending": [assignment],
        }.get(status, [])
    )
    api.get_program = AsyncMock(
        return_value=ProgramDTO(
            id=assignment.program_id,
            company_id=assignment.company_id,
            title="Important course",
            is_active=True,
        )
    )
    api.get_progress = AsyncMock(
        return_value=AssignmentProgressDTO(percentage=0, items=[])
    )
    api.first_incomplete_step = MagicMock(return_value=None)
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 42
    message.chat = MagicMock()
    message.chat.id = 42
    message.answer = AsyncMock()
    await active_assignments(message, api, _state())
    kwargs = message.answer.await_args.kwargs
    assert kwargs.get("reply_markup") is not None
