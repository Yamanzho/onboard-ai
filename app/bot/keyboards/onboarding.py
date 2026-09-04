from typing import Any
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

COMPLETE_CALLBACK_PREFIX = "progress:complete:"
QUIZ_SELECT_PREFIX = "qsel:"
QUIZ_CONFIRM_PREFIX = "qok:"
_BUTTON_TEXT_MAX = 64


def complete_step_keyboard(
    progress_id: UUID,
    *,
    label: str = "✅ Выполнено",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
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


def parse_quiz_select_callback(data: str) -> tuple[int, str] | None:
    if not data.startswith(QUIZ_SELECT_PREFIX):
        return None
    raw = data.removeprefix(QUIZ_SELECT_PREFIX)
    question_raw, sep, option_id = raw.partition(":")
    if not sep or not option_id:
        return None
    try:
        return int(question_raw), option_id
    except ValueError:
        return None


def parse_quiz_confirm_callback(data: str) -> int | None:
    if not data.startswith(QUIZ_CONFIRM_PREFIX):
        return None
    raw = data.removeprefix(QUIZ_CONFIRM_PREFIX)
    try:
        return int(raw)
    except ValueError:
        return None


def quiz_options_keyboard(
    question_index: int,
    options: list[dict[str, Any]],
    *,
    multiple: bool,
    selected: set[str] | None = None,
) -> InlineKeyboardMarkup:
    chosen = selected or set()
    rows: list[list[InlineKeyboardButton]] = []
    for option in options:
        option_id = str(option.get("id") or "")
        label = str(option.get("text") or option_id)
        if multiple:
            mark = "☑" if option_id in chosen else "☐"
            label = f"{mark} {label}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label[:_BUTTON_TEXT_MAX],
                    callback_data=f"{QUIZ_SELECT_PREFIX}{question_index}:{option_id}"[
                        :64
                    ],
                )
            ]
        )
    if multiple:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить ответ",
                    callback_data=f"{QUIZ_CONFIRM_PREFIX}{question_index}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
