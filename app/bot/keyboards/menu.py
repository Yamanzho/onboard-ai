from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

MENU_MY_ONBOARDING = "📚 Мой онбординг"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MENU_MY_ONBOARDING)]],
        resize_keyboard=True,
        input_field_placeholder="Выберите пункт меню",
    )
