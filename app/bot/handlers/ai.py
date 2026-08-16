"""Catch-all Telegram AI client for POST /api/v1/ai/chat.

Registered last: /start → onboarding FSM → cabinet → AI.
Does not query vector tables, call the LLM provider, or select a tenant.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import default_state
from aiogram.types import Message

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.api.schemas import EmployeeDTO
from app.bot.keyboards.menu import (
    MENU_ACTIVE,
    MENU_CALENDAR,
    MENU_COMPANY,
    MENU_HISTORY,
    MENU_MY_ONBOARDING,
    MENU_PROFILE,
)
from app.bot.services.ai_client import (
    MSG_NEW_CHAT,
    MSG_UNAUTHENTICATED,
    MSG_UNAVAILABLE,
    MSG_VALIDATION,
    ask_company_knowledge,
)
from app.bot.services.ai_conversation import get_telegram_conversation_store
from app.core.ai_constants import MAX_CHAT_QUESTION_CHARS
from app.core.exceptions import ServiceUnavailableError

router = Router(name="ai")

_MENU_TEXTS = frozenset(
    {
        MENU_MY_ONBOARDING,
        MENU_ACTIVE,
        MENU_HISTORY,
        MENU_CALENDAR,
        MENU_COMPANY,
        MENU_PROFILE,
    }
)

_EMPTY_QUESTION = "Напишите вопрос по базе знаний компании."
_ARCHIVED = "Ваш аккаунт архивирован. Обратитесь к HR."
_SERVER_UNAVAILABLE = "Не удалось связаться с сервером. Попробуйте позже."


async def _require_employee(
    message: Message,
    api: OnboardApiClient,
) -> EmployeeDTO | None:
    if message.from_user is None:
        return None
    try:
        employee = await api.find_employee_by_telegram(message.from_user.id)
    except OnboardApiError as exc:
        if exc.status_code == 403:
            await message.answer(_ARCHIVED)
            return None
        await message.answer(_SERVER_UNAVAILABLE)
        return None
    if employee is None:
        await message.answer(MSG_UNAUTHENTICATED)
        return None
    if employee.status == "archived":
        await message.answer(_ARCHIVED)
        return None
    return employee


async def _send_typing(message: Message) -> None:
    bot = getattr(message, "bot", None)
    chat = getattr(message, "chat", None)
    if bot is None or chat is None:
        return
    try:
        await bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
    except Exception:
        return


@router.message(StateFilter(default_state), Command("newchat"))
async def cmd_newchat(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    if await state.get_state() is not None:
        return
    if await _require_employee(message, api) is None:
        return
    if message.from_user is None:
        return
    try:
        await get_telegram_conversation_store().clear_current_conversation(
            message.from_user.id
        )
    except ServiceUnavailableError:
        await message.answer(MSG_UNAVAILABLE)
        return
    await message.answer(MSG_NEW_CHAT)


@router.message(
    StateFilter(default_state),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(_MENU_TEXTS),
)
async def ai_question(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    if await state.get_state() is not None:
        return

    raw = message.text or ""
    text = raw.strip()
    if text.startswith("/") or text in _MENU_TEXTS:
        return
    if not text:
        await message.answer(_EMPTY_QUESTION)
        return
    if len(text) > MAX_CHAT_QUESTION_CHARS:
        await message.answer(MSG_VALIDATION)
        return

    if await _require_employee(message, api) is None:
        return
    if message.from_user is None:
        return

    await _send_typing(message)
    reply = await ask_company_knowledge(
        api,
        text,
        telegram_user_id=message.from_user.id,
    )
    await message.answer(reply)
