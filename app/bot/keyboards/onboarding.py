from typing import Any
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

COMPLETE_CALLBACK_PREFIX = "progress:complete:"
BLOCK_NEXT_PREFIX = "pnext:"
BLOCK_READ_PREFIX = "pread:"
ASSIGN_OPEN_PREFIX = "aopen:"
ACK_VIEW_PREFIX = "ackv:"
ACK_CONFIRM_PREFIX = "acky:"
REMIND_ACK_PREFIX = "rack:"
REMIND_REDUCE_PREFIX = "rred:"
REMIND_DISABLE_PREFIX = "rdis:"
QUIZ_RETRY_PREFIX = "qretry:"
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


def _parse_uuid_index(data: str, prefix: str) -> tuple[UUID, int] | None:
    if not data.startswith(prefix):
        return None
    raw = data.removeprefix(prefix)
    id_raw, sep, index_raw = raw.partition(":")
    if not sep:
        return None
    try:
        return UUID(id_raw), int(index_raw)
    except ValueError:
        return None


def parse_block_next_callback(data: str) -> tuple[UUID, int] | None:
    return _parse_uuid_index(data, BLOCK_NEXT_PREFIX)


def parse_block_read_callback(data: str) -> tuple[UUID, int] | None:
    return _parse_uuid_index(data, BLOCK_READ_PREFIX)


def parse_assign_open_callback(data: str) -> UUID | None:
    if not data.startswith(ASSIGN_OPEN_PREFIX):
        return None
    try:
        return UUID(data.removeprefix(ASSIGN_OPEN_PREFIX))
    except ValueError:
        return None


def _parse_uuid_prefix(data: str, prefix: str) -> UUID | None:
    if not data.startswith(prefix):
        return None
    try:
        return UUID(data.removeprefix(prefix))
    except ValueError:
        return None


def parse_remind_ack_callback(data: str) -> UUID | None:
    return _parse_uuid_prefix(data, REMIND_ACK_PREFIX)


def parse_remind_reduce_callback(data: str) -> UUID | None:
    return _parse_uuid_prefix(data, REMIND_REDUCE_PREFIX)


def parse_remind_disable_callback(data: str) -> UUID | None:
    return _parse_uuid_prefix(data, REMIND_DISABLE_PREFIX)


def assignment_notice_keyboard(assignment_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть",
                    callback_data=f"{ASSIGN_OPEN_PREFIX}{assignment_id}",
                )
            ]
        ]
    )


def reminder_keyboard(assignment_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть",
                    callback_data=f"{ASSIGN_OPEN_PREFIX}{assignment_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Понял",
                    callback_data=f"{REMIND_ACK_PREFIX}{assignment_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Напоминать реже",
                    callback_data=f"{REMIND_REDUCE_PREFIX}{assignment_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не напоминать больше",
                    callback_data=f"{REMIND_DISABLE_PREFIX}{assignment_id}",
                )
            ],
        ]
    )


def parse_quiz_retry_callback(data: str) -> UUID | None:
    if not data.startswith(QUIZ_RETRY_PREFIX):
        return None
    try:
        return UUID(data.removeprefix(QUIZ_RETRY_PREFIX))
    except ValueError:
        return None


def content_block_keyboard(
    progress_id: UUID,
    *,
    block_index: int,
    is_final: bool,
) -> InlineKeyboardMarkup:
    if is_final:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Прочитал",
                        callback_data=f"{BLOCK_READ_PREFIX}{progress_id}:{block_index}",
                    )
                ]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Далее",
                    callback_data=f"{BLOCK_NEXT_PREFIX}{progress_id}:{block_index}",
                )
            ]
        ]
    )


def parse_ack_view_callback(data: str) -> UUID | None:
    return _parse_uuid_prefix(data, ACK_VIEW_PREFIX)


def parse_ack_confirm_callback(data: str) -> UUID | None:
    return _parse_uuid_prefix(data, ACK_CONFIRM_PREFIX)


def acknowledgement_open_keyboard(item_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть документ",
                    callback_data=f"{ACK_VIEW_PREFIX}{item_id}",
                )
            ]
        ]
    )


def acknowledgement_confirm_keyboard(item_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Я ознакомился",
                    callback_data=f"{ACK_CONFIRM_PREFIX}{item_id}",
                )
            ]
        ]
    )


def assignment_open_keyboard(assignments: list[tuple[UUID, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for assignment_id, title in assignments:
        rows.append(
            [
                InlineKeyboardButton(
                    text=title[:_BUTTON_TEXT_MAX],
                    callback_data=f"{ASSIGN_OPEN_PREFIX}{assignment_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quiz_retry_keyboard(progress_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Попробовать снова",
                    callback_data=f"{QUIZ_RETRY_PREFIX}{progress_id}",
                )
            ]
        ]
    )


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
