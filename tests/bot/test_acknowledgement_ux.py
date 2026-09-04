"""Phase 9H: Telegram acknowledgement flow, order, and stale callbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.api.schemas import (
    AcknowledgementActionDTO,
    AcknowledgementDocumentDTO,
    AcknowledgementItemDTO,
    AcknowledgementListDTO,
    AcknowledgementSummaryDTO,
    AssignmentDTO,
    EmployeeDTO,
)
from app.bot.handlers.acknowledgement import (
    format_acknowledgement_body,
    format_acknowledgement_intro,
    show_acknowledgement_assignment,
)
from app.bot.handlers.cabinet import active_assignments
from app.bot.handlers.onboarding import (
    acknowledgement_confirm_callback,
    acknowledgement_view_callback,
    my_onboarding,
    open_assignment_callback,
)
from app.bot.keyboards.menu import MENU_ACTIVE, MENU_MY_ONBOARDING
from app.bot.keyboards.onboarding import (
    ACK_CONFIRM_PREFIX,
    ACK_VIEW_PREFIX,
    acknowledgement_confirm_keyboard,
    acknowledgement_open_keyboard,
    parse_ack_confirm_callback,
    parse_ack_view_callback,
)

pytestmark = pytest.mark.telegram


def test_ack_keyboards_and_parsers() -> None:
    item_id = uuid4()
    open_kb = acknowledgement_open_keyboard(item_id)
    assert open_kb.inline_keyboard[0][0].text == "Открыть документ"
    assert parse_ack_view_callback(open_kb.inline_keyboard[0][0].callback_data) == item_id
    confirm = acknowledgement_confirm_keyboard(item_id)
    assert confirm.inline_keyboard[0][0].text == "Я ознакомился"
    assert "Подписать" not in confirm.inline_keyboard[0][0].text
    assert parse_ack_confirm_callback(confirm.inline_keyboard[0][0].callback_data) == item_id
    assert ACK_VIEW_PREFIX.startswith("ackv")
    assert ACK_CONFIRM_PREFIX.startswith("acky")


def test_intro_and_truncated_body() -> None:
    item = AcknowledgementItemDTO(
        id=uuid4(),
        assignment_id=uuid4(),
        article_id=uuid4(),
        article_version_id=uuid4(),
        position=2,
        is_required=True,
        title="Политика информационной безопасности",
        version=3,
    )
    intro = format_acknowledgement_intro(item=item, total=3)
    assert "Вам необходимо ознакомиться с документами." in intro
    assert "Документ 2/3" in intro
    assert "Политика информационной безопасности" in intro
    assert "обязательный" in intro
    long_body = "x" * 4000
    rendered = format_acknowledgement_body(long_body)
    assert "документ длинный" in rendered
    assert "электронн" not in rendered.lower()
    assert "подпис" not in rendered.lower()


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


def _message() -> MagicMock:
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 42
    message.chat = MagicMock()
    message.chat.id = 42
    message.answer = AsyncMock()
    message.text = MENU_MY_ONBOARDING
    return message


def _item(
    *,
    position: int,
    required: bool = True,
    acknowledged: bool = False,
    title: str | None = None,
) -> AcknowledgementItemDTO:
    return AcknowledgementItemDTO(
        id=uuid4(),
        assignment_id=uuid4(),
        article_id=uuid4(),
        article_version_id=uuid4(),
        position=position,
        is_required=required,
        acknowledged_at=datetime.now(UTC) if acknowledged else None,
        title=title or f"Doc {position}",
        version=1,
    )


def _listing(
    items: list[AcknowledgementItemDTO],
    *,
    status: str = "in_progress",
    assignment_id=None,
) -> AcknowledgementListDTO:
    assignment_id = assignment_id or uuid4()
    required = [item for item in items if item.is_required]
    done = [item for item in required if item.acknowledged_at is not None]
    return AcknowledgementListDTO(
        items=items,
        assignment_id=assignment_id,
        assignment_status=status,
        acknowledgement=AcknowledgementSummaryDTO(
            total_documents=len(items),
            required_documents=len(required),
            acknowledged_required_count=len(done),
            completed=len(done) == len(required),
            title=items[0].title if items else "Docs",
            percentage=100.0 if required and len(done) == len(required) else 0.0,
        ),
    )


def _assignment(*, assignment_id=None, status: str = "pending") -> AssignmentDTO:
    return AssignmentDTO(
        id=assignment_id or uuid4(),
        company_id=uuid4(),
        employee_id=uuid4(),
        assignment_type="acknowledgement",
        program_id=None,
        status=status,
        assigned_at=datetime.now(UTC),
        due_at=None,
        acknowledgement=AcknowledgementSummaryDTO(
            total_documents=2,
            required_documents=2,
            acknowledged_required_count=0,
            title="Политика",
        ),
    )


@pytest.mark.asyncio
async def test_active_list_includes_acknowledgement() -> None:
    assignment = _assignment()
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
    first = _item(position=1, title="Политика информационной безопасности")
    api.list_acknowledgements = AsyncMock(
        return_value=_listing([first], assignment_id=assignment.id)
    )
    message = _message()
    message.text = MENU_ACTIVE
    await active_assignments(message, api, _state())
    text = message.answer.await_args.args[0]
    assert "Политика информационной безопасности" in text or "Политика" in text


@pytest.mark.asyncio
async def test_open_does_not_acknowledge_then_confirm_advances() -> None:
    assignment_id = uuid4()
    first = _item(position=1, title="One")
    second = _item(position=2, title="Two")
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.list_acknowledgements = AsyncMock(
        return_value=_listing([first, second], assignment_id=assignment_id)
    )
    api.get_acknowledgement_document = AsyncMock(
        return_value=AcknowledgementDocumentDTO(
            item=first,
            body="Exact assigned body",
            assignment_status="in_progress",
        )
    )
    message = _message()
    state = _state()
    await show_acknowledgement_assignment(
        message=message,
        api=api,
        state=state,
        assignment_id=assignment_id,
    )
    intro = message.answer.await_args.args[0]
    assert "Документ 1/2" in intro
    assert "Открыть документ" in str(message.answer.await_args.kwargs["reply_markup"])

    callback = _callback(f"{ACK_VIEW_PREFIX}{first.id}")
    await acknowledgement_view_callback(
        callback,
        api,
        _state({"assignment_id": str(assignment_id)}),
    )
    api.get_acknowledgement_document.assert_awaited_once()
    rendered = callback.message.edit_text.await_args.args[0]
    assert "Exact assigned body" in rendered
    assert "Я ознакомился" in str(callback.message.edit_text.await_args.kwargs["reply_markup"])
    api.acknowledge_document.assert_not_awaited()

    after_first = AcknowledgementItemDTO(
        **{**first.model_dump(), "acknowledged_at": datetime.now(UTC)}
    )
    api.acknowledge_document = AsyncMock(
        return_value=AcknowledgementActionDTO(
            item=after_first,
            assignment_status="in_progress",
            acknowledgement=AcknowledgementSummaryDTO(
                total_documents=2,
                required_documents=2,
                acknowledged_required_count=1,
                completed=False,
            ),
        )
    )
    api.list_acknowledgements = AsyncMock(
        return_value=_listing([after_first, second], assignment_id=assignment_id)
    )
    confirm = _callback(f"{ACK_CONFIRM_PREFIX}{first.id}")
    await acknowledgement_confirm_callback(
        confirm,
        api,
        _state({"assignment_id": str(assignment_id)}),
    )
    next_text = confirm.message.edit_text.await_args.args[0]
    assert "Документ 2/2" in next_text
    assert "Two" in next_text


@pytest.mark.asyncio
async def test_final_required_completes_and_double_ack_safe() -> None:
    assignment_id = uuid4()
    only = _item(position=1, title="Only")
    acked = AcknowledgementItemDTO(
        **{**only.model_dump(), "acknowledged_at": datetime.now(UTC)}
    )
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.acknowledge_document = AsyncMock(
        return_value=AcknowledgementActionDTO(
            item=acked,
            assignment_status="completed",
            acknowledgement=AcknowledgementSummaryDTO(
                total_documents=1,
                required_documents=1,
                acknowledged_required_count=1,
                completed=True,
            ),
        )
    )
    api.list_acknowledgements = AsyncMock(
        return_value=_listing([acked], status="completed", assignment_id=assignment_id)
    )
    first = _callback(f"{ACK_CONFIRM_PREFIX}{only.id}")
    await acknowledgement_confirm_callback(
        first,
        api,
        _state({"assignment_id": str(assignment_id)}),
    )
    assert "завершено" in first.message.edit_text.await_args.args[0].lower()

    second = _callback(f"{ACK_CONFIRM_PREFIX}{only.id}")
    await acknowledgement_confirm_callback(
        second,
        api,
        _state({"assignment_id": str(assignment_id)}),
    )
    assert api.acknowledge_document.await_count == 2
    assert "завершено" in second.message.edit_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_stale_completed_and_cancelled_callbacks_are_friendly() -> None:
    assignment_id = uuid4()
    api = AsyncMock(spec=OnboardApiClient)
    api.ensure_session = AsyncMock(return_value=True)
    api.get_assignment = AsyncMock(
        return_value=_assignment(assignment_id=assignment_id, status="completed")
    )
    callback = _callback(f"aopen:{assignment_id}")
    await open_assignment_callback(callback, api, _state())
    assert "завершено" in callback.message.edit_text.await_args.args[0].lower()

    api.get_assignment = AsyncMock(
        return_value=_assignment(assignment_id=assignment_id, status="cancelled")
    )
    cancelled = _callback(f"aopen:{assignment_id}")
    await open_assignment_callback(cancelled, api, _state())
    assert "отменено" in cancelled.message.edit_text.await_args.args[0].lower()

    api.acknowledge_document = AsyncMock(
        side_effect=OnboardApiError("cancelled", status_code=400, detail="cancelled")
    )
    stale = _callback(f"{ACK_CONFIRM_PREFIX}{uuid4()}")
    await acknowledgement_confirm_callback(
        stale,
        api,
        _state({"assignment_id": str(assignment_id)}),
    )
    stale.answer.assert_awaited()
    assert "отменено" in stale.answer.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_my_onboarding_opens_acknowledgement() -> None:
    assignment = _assignment()
    item = _item(position=1, title="Code of Conduct")
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
    api.list_acknowledgements = AsyncMock(
        return_value=_listing([item], assignment_id=assignment.id)
    )
    message = _message()
    await my_onboarding(message, api, _state())
    text = message.answer.await_args.args[0]
    assert "Вам необходимо ознакомиться с документами." in text
    assert "Code of Conduct" in text
