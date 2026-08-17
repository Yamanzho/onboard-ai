"""All six Telegram menu buttons resolve identity via find_employee_by_telegram."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.api.schemas import EmployeeDTO
from app.bot.handlers.cabinet import (
    active_assignments,
    calendar_view,
    company_view,
    history_assignments,
    profile_view,
)
from app.bot.handlers.onboarding import my_onboarding
from app.bot.handlers.start import cmd_start
from app.bot.keyboards.menu import (
    MENU_ACTIVE,
    MENU_CALENDAR,
    MENU_COMPANY,
    MENU_HISTORY,
    MENU_MY_ONBOARDING,
    MENU_PROFILE,
)

pytestmark = [pytest.mark.security, pytest.mark.telegram]

TEST_ID = 9_400_000_042
CHAT_ID = 9_400_000_042

NOT_REGISTERED_CABINET = (
    "Вы ещё не добавлены в OnboardAI.\n"
    "Обратитесь к HR, чтобы вас зарегистрировали."
)


def _employee() -> EmployeeDTO:
    return EmployeeDTO(
        id=uuid4(),
        company_id=uuid4(),
        telegram_user_id=TEST_ID,
        full_name="Ada Lovelace",
        role="employee",
        status="active",
    )


def _message(text: str, *, user_id: int = TEST_ID) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.from_user = MagicMock()
    message.from_user.id = user_id
    message.from_user.full_name = "Ada"
    message.from_user.username = "ada"
    message.chat = MagicMock()
    message.chat.id = CHAT_ID
    message.answer = AsyncMock()
    return message


def _state() -> AsyncMock:
    state = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.update_data = AsyncMock()
    return state


CABINET_HANDLERS = (
    (MENU_MY_ONBOARDING, my_onboarding, "my_onboarding"),
    (MENU_ACTIVE, active_assignments, "active_assignments"),
    (MENU_HISTORY, history_assignments, "history_assignments"),
    (MENU_CALENDAR, calendar_view, "calendar_view"),
    (MENU_COMPANY, company_view, "company_view"),
    (MENU_PROFILE, profile_view, "profile_view"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("menu_text", "handler", "handler_name"),
    CABINET_HANDLERS,
    ids=[name for _, _, name in CABINET_HANDLERS],
)
async def test_unregistered_telegram_id_all_six_buttons(
    menu_text: str,
    handler,
    handler_name: str,
) -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=None)
    message = _message(menu_text)
    await handler(message, api, _state())
    api.find_employee_by_telegram.assert_awaited_once()
    called_id = api.find_employee_by_telegram.await_args.args[0]
    assert called_id == TEST_ID
    kwargs = api.find_employee_by_telegram.await_args.kwargs
    assert kwargs["handler"] == handler_name
    assert kwargs["chat_id"] == CHAT_ID
    message.answer.assert_awaited_once_with(NOT_REGISTERED_CABINET)
    api.list_assignments.assert_not_called()
    api.get_me.assert_not_called()


@pytest.mark.asyncio
async def test_start_without_invite_token_not_found() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(return_value=None)
    message = _message("/start")
    command = MagicMock()
    command.args = None
    await cmd_start(message, _state(), command, api)
    api.find_employee_by_telegram.assert_awaited_once()
    assert api.find_employee_by_telegram.await_args.args[0] == TEST_ID
    sent = message.answer.await_args.args[0]
    assert "Вы ещё не добавлены в OnboardAI." in sent
    assert "персональную ссылку-приглашение" in sent


@pytest.mark.asyncio
async def test_matching_active_employee_profile_continues() -> None:
    api = AsyncMock(spec=OnboardApiClient)
    employee = _employee()
    api.find_employee_by_telegram = AsyncMock(return_value=employee)
    api.get_me = AsyncMock(return_value=employee)
    message = _message(MENU_PROFILE)
    await profile_view(message, api, _state())
    api.find_employee_by_telegram.assert_awaited_once()
    assert api.find_employee_by_telegram.await_args.args[0] == TEST_ID
    api.get_me.assert_awaited()
    sent = message.answer.await_args.args[0]
    assert "Мой профиль" in sent
    assert "Ada Lovelace" in sent


@pytest.mark.asyncio
async def test_invited_status_is_not_the_not_registered_copy() -> None:
    """Bot login 403 (invited/archived) must not look like 'not registered'."""
    api = AsyncMock(spec=OnboardApiClient)
    api.find_employee_by_telegram = AsyncMock(
        side_effect=OnboardApiError(
            "Please accept your invite and set a password first",
            status_code=403,
        )
    )
    message = _message(MENU_PROFILE)
    await profile_view(message, api, _state())
    sent = message.answer.await_args.args[0]
    assert sent == "Не удалось связаться с сервером. Попробуйте позже."
    assert "не добавлены" not in sent
