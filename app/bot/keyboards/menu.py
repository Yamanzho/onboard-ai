from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

MENU_MY_ONBOARDING = "📚 Мой онбординг"
MENU_ACTIVE = "🔥 Активные"
MENU_HISTORY = "📜 История"
MENU_CALENDAR = "📅 Календарь"
MENU_COMPANY = "🏢 Компания"
MENU_PROFILE = "👤 Профиль"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=MENU_MY_ONBOARDING),
                KeyboardButton(text=MENU_ACTIVE),
            ],
            [
                KeyboardButton(text=MENU_HISTORY),
                KeyboardButton(text=MENU_CALENDAR),
            ],
            [
                KeyboardButton(text=MENU_COMPANY),
                KeyboardButton(text=MENU_PROFILE),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите пункт меню",
    )
