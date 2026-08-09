from html import escape

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.keyboards.menu import main_menu_keyboard

router = Router(name="start")


def _invite_error_message(exc: OnboardApiError) -> str:
    detail = str(exc).lower()
    if "already used" in detail:
        return "Это приглашение уже использовано."
    if "expired" in detail:
        return "Ссылка приглашения истекла."
    if "already linked" in detail:
        return "Этот Telegram аккаунт уже связан с другим профилем."
    if "another telegram" in detail:
        return "Этот профиль уже связан с другим Telegram аккаунтом."
    return (
        "Не удалось принять приглашение.\n"
        "Ссылка могла истечь, уже использована, или это не приглашение "
        "сотрудника.\n\n"
        "Обратитесь к HR за новой ссылкой."
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    command: CommandObject,
    api: OnboardApiClient,
) -> None:
    await state.clear()
    name = message.from_user.full_name if message.from_user else "коллега"
    invite_token = (command.args or "").strip()

    if invite_token and message.from_user is not None:
        # Drop any stale JWT cache before bind so we never keep another identity.
        api.invalidate_session(message.from_user.id)
        try:
            employee = await api.accept_invite_via_telegram(
                token=invite_token,
                telegram_user_id=message.from_user.id,
                telegram_username=message.from_user.username,
                telegram_chat_id=message.chat.id if message.chat else None,
            )
        except OnboardApiError as exc:
            # Do not echo the invite token or leak invite/tenant details.
            await message.answer(
                _invite_error_message(exc),
                reply_markup=main_menu_keyboard(),
            )
            return

        display_name = escape(employee.full_name or name)
        await message.answer(
            f"Добро пожаловать, {display_name}!\n\n"
            "Выберите раздел в меню:",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer(
        f"Привет, {escape(name)}!\n\n"
        "Я бот OnboardAI — помогу пройти онбординг.\n"
        "Открой меню и выбери нужный раздел.",
        reply_markup=main_menu_keyboard(),
    )
