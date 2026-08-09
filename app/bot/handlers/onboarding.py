from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.api.schemas import ProgressItemDTO
from app.bot.handlers.step_content import format_step_message
from app.bot.keyboards.menu import MENU_MY_ONBOARDING
from app.bot.keyboards.onboarding import complete_step_keyboard, parse_complete_callback
from app.bot.states.onboarding import OnboardingStates

router = Router(name="onboarding")

_STATUS_LABELS = {
    "not_started": "не начат",
    "in_progress": "в процессе",
    "completed": "выполнен",
    "skipped": "пропущен",
}


def _format_step_message(
    *,
    program_title: str,
    percentage: float,
    step_number: int,
    total_steps: int,
    item: ProgressItemDTO,
) -> str:
    status = _STATUS_LABELS.get(item.status, item.status)
    step = item.step
    return format_step_message(
        program_title=program_title,
        percentage=percentage,
        step_number=step_number,
        total_steps=total_steps,
        status_label=status,
        step_title=step.title if step is not None else None,
        step_description=step.description if step is not None else None,
        step_content=step.content if step is not None else None,
    )


async def _show_current_step(
    *,
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
    assignment_id: UUID,
    program_id: UUID,
    edit: bool = False,
) -> None:
    program = await api.get_program(program_id)
    progress = await api.get_progress(assignment_id)
    current = api.first_incomplete_step(progress)

    if current is None:
        await state.clear()
        text = (
            f"🎉 <b>Поздравляем!</b>\n\n"
            f"Вы завершили программу «{escape(program.title)}».\n"
            f"Прогресс: {progress.percentage:.0f}%."
        )
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        return

    step_number, item = current
    await state.set_state(OnboardingStates.viewing_step)
    await state.update_data(
        assignment_id=str(assignment_id),
        program_id=str(program_id),
        progress_id=str(item.id),
    )
    text = _format_step_message(
        program_title=program.title,
        percentage=progress.percentage,
        step_number=step_number,
        total_steps=len(progress.items),
        item=item,
    )
    markup = complete_step_keyboard(item.id)
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.message(F.text == MENU_MY_ONBOARDING)
async def my_onboarding(message: Message, api: OnboardApiClient, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        employee = await api.find_employee_by_telegram(message.from_user.id)
    except OnboardApiError:
        await message.answer("Не удалось связаться с сервером. Попробуйте позже.")
        return

    if employee is None:
        await message.answer(
            "Вы ещё не добавлены в OnboardAI.\n"
            "Обратитесь к HR, чтобы вас зарегистрировали."
        )
        return

    if employee.status == "archived":
        await message.answer("Ваш аккаунт архивирован. Обратитесь к HR.")
        return

    await state.update_data(telegram_user_id=message.from_user.id)

    try:
        assignment = await api.get_active_assignment(employee.id)
    except OnboardApiError:
        await message.answer("Не удалось загрузить назначения. Попробуйте позже.")
        return

    if assignment is None:
        await state.clear()
        await message.answer(
            "Telegram подключён, но онбординг ещё не назначен.\n"
            "Когда HR назначит программу — она появится здесь."
        )
        return

    try:
        await _show_current_step(
            message=message,
            api=api,
            state=state,
            assignment_id=assignment.id,
            program_id=assignment.program_id,
        )
    except OnboardApiError:
        await message.answer("Не удалось загрузить прогресс. Попробуйте позже.")


@router.callback_query(F.data.startswith("progress:complete:"))
async def complete_step_callback(
    callback: CallbackQuery,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return

    progress_id = parse_complete_callback(callback.data)
    if progress_id is None:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return

    data = await state.get_data()
    assignment_id_raw = data.get("assignment_id")
    program_id_raw = data.get("program_id")
    telegram_user_id = data.get("telegram_user_id")
    if assignment_id_raw is None or program_id_raw is None:
        await callback.answer(
            "Сессия устарела. Откройте «Мой онбординг» снова.",
            show_alert=True,
        )
        return

    user_id = telegram_user_id or (
        callback.from_user.id if callback.from_user is not None else None
    )
    if user_id is None or not await api.ensure_session(int(user_id)):
        await callback.answer(
            "Сессия устарела. Откройте «Мой онбординг» снова.",
            show_alert=True,
        )
        return

    try:
        await api.complete_progress(progress_id)
    except OnboardApiError as exc:
        if exc.status_code == 409:
            await callback.answer("Шаг уже выполнен", show_alert=True)
        else:
            await callback.answer("Не удалось отметить шаг", show_alert=True)
            return
    else:
        await callback.answer("Отлично!")

    try:
        await _show_current_step(
            message=callback.message,
            api=api,
            state=state,
            assignment_id=UUID(assignment_id_raw),
            program_id=UUID(program_id_raw),
            edit=True,
        )
    except OnboardApiError:
        await callback.message.edit_text(
            "Не удалось обновить прогресс. Откройте «Мой онбординг» снова."
        )
