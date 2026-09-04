from html import escape
from uuid import UUID

from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, Message

from app.bot.api.client import OnboardApiClient
from app.bot.api.schemas import AcknowledgementItemDTO, AssignmentDTO
from app.bot.keyboards.onboarding import (
    acknowledgement_confirm_keyboard,
    acknowledgement_open_keyboard,
)

_TELEGRAM_BODY_LIMIT = 3500


def assignment_label(assignment: AssignmentDTO) -> str:
    summary = assignment.acknowledgement
    title = summary.title if summary is not None else None
    if isinstance(title, str) and title.strip():
        return title
    return "Ознакомление с документами"


def format_acknowledgement_intro(
    *,
    item: AcknowledgementItemDTO,
    total: int,
) -> str:
    kind = "обязательный" if item.is_required else "необязательный"
    return (
        "Вам необходимо ознакомиться с документами.\n\n"
        f"Документ {item.position}/{total}\n"
        f"«{escape(item.title)}»\n"
        f"{kind} · версия {item.version}"
    )


def format_acknowledgement_body(body: str) -> str:
    text = body.strip()
    if len(text) <= _TELEGRAM_BODY_LIMIT:
        return escape(text)
    return (
        escape(text[:_TELEGRAM_BODY_LIMIT].rstrip())
        + "\n\n…документ длинный. Полный текст доступен в веб-кабинете."
    )


def _next_required(items: list[AcknowledgementItemDTO]) -> AcknowledgementItemDTO | None:
    for item in items:
        if item.is_required and item.acknowledged_at is None:
            return item
    return None


async def show_acknowledgement_assignment(
    *,
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
    assignment_id: UUID,
    edit: bool = False,
) -> None:
    listing = await api.list_acknowledgements(assignment_id)
    if listing.assignment_status == "completed":
        await state.clear()
        text = "Ознакомление с документами завершено."
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        return
    if listing.assignment_status == "cancelled":
        await state.clear()
        text = "Это назначение отменено."
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        return

    current = _next_required(listing.items)
    if current is None:
        await state.clear()
        text = "Ознакомление с документами завершено."
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        return

    await state.update_data(
        assignment_id=str(assignment_id),
        ack_item_id=str(current.id),
        assignment_type="acknowledgement",
    )
    text = format_acknowledgement_intro(item=current, total=len(listing.items))
    markup = acknowledgement_open_keyboard(current.id)
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


async def show_acknowledgement_document(
    *,
    message: Message,
    api: OnboardApiClient,
    assignment_id: UUID,
    item_id: UUID,
    edit: bool = False,
) -> None:
    viewed = await api.get_acknowledgement_document(assignment_id, item_id)
    listing = await api.list_acknowledgements(assignment_id)
    intro = format_acknowledgement_intro(item=viewed.item, total=len(listing.items))
    body = format_acknowledgement_body(viewed.body)
    text = f"{intro}\n\n{body}"
    markup: InlineKeyboardMarkup | None = None
    if viewed.item.acknowledged_at is None and viewed.assignment_status in {
        "pending",
        "in_progress",
    }:
        markup = acknowledgement_confirm_keyboard(item_id)
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)
