from html import escape

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.keyboards.menu import main_menu_keyboard

router = Router(name="start")


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
        try:
            await api.accept_invite_via_telegram(
                token=invite_token,
                telegram_user_id=message.from_user.id,
                telegram_username=message.from_user.username,
                telegram_chat_id=message.chat.id if message.chat else None,
            )
        except OnboardApiError:
            # Do not echo the invite token or leak invite/tenant details.
            await message.answer(
                "Не удалось принять приглашение.\n"
                "Ссылка могла истечь, уже использована, или это не приглашение "
                "сотрудника.\n\n"
                "Обратитесь к HR за новой ссылкой.",
                reply_markup=main_menu_keyboard(),
            )
            return

        await message.answer(
            f"Добро пожаловать в OnboardAI 👋\n\n"
            f"Ваш Telegram подключён к профилю сотрудника, "
            f"{escape(name)}.\n\n"
            f"Если онбординг уже назначен — откройте «📚 Мой онбординг».\n"
            f"Если ещё не назначен — подождите, пока HR назначит программу.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer(
        f"Привет, {escape(name)}!\n\n"
        "Я бот OnboardAI — помогу пройти онбординг.\n"
        "Открой меню и выбери «📚 Мой онбординг».",
        reply_markup=main_menu_keyboard(),
    )
