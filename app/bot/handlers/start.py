from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards.menu import main_menu_keyboard

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.from_user.full_name if message.from_user else "коллега"
    await message.answer(
        f"Привет, {name}!\n\n"
        "Я бот OnboardAI — помогу пройти онбординг.\n"
        "Открой меню и выбери «📚 Мой онбординг».",
        reply_markup=main_menu_keyboard(),
    )
