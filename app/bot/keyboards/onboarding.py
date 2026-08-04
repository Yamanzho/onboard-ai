from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

COMPLETE_CALLBACK_PREFIX = "progress:complete:"


def complete_step_keyboard(progress_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выполнено",
                    callback_data=f"{COMPLETE_CALLBACK_PREFIX}{progress_id}",
                )
            ]
        ]
    )


def parse_complete_callback(data: str) -> UUID | None:
    if not data.startswith(COMPLETE_CALLBACK_PREFIX):
        return None
    raw = data.removeprefix(COMPLETE_CALLBACK_PREFIX)
    try:
        return UUID(raw)
    except ValueError:
        return None
