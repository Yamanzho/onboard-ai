from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.api.schemas import ProgressItemDTO
from app.bot.handlers.step_content import format_step_message
from app.bot.keyboards.menu import (
    MENU_ACTIVE,
    MENU_CALENDAR,
    MENU_COMPANY,
    MENU_HISTORY,
    MENU_MY_ONBOARDING,
    MENU_PROFILE,
)
from app.bot.keyboards.onboarding import complete_step_keyboard, parse_complete_callback
from app.bot.services.outbound_delivery import TelegramOutboundExecutor
from app.bot.states.onboarding import OnboardingStates
from app.services.step_content import parse_questions

router = Router(name="onboarding")

_DONE_STATUSES = frozenset({"completed", "skipped"})

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
    step_type = item.step.step_type if item.step is not None else "content"
    existing = await state.get_data()
    await state.set_state(OnboardingStates.viewing_step)
    await state.update_data(
        assignment_id=str(assignment_id),
        program_id=str(program_id),
        progress_id=str(item.id),
        step_type=step_type,
        telegram_user_id=(
            message.from_user.id
            if message.from_user is not None
            else existing.get("telegram_user_id")
        ),
    )
    text = _format_step_message(
        program_title=program.title,
        percentage=progress.percentage,
        step_number=step_number,
        total_steps=len(progress.items),
        item=item,
    )
    markup = None
    if step_type == "quiz":
        questions = parse_questions(item.step.content if item.step else None)
        await state.set_state(OnboardingStates.answering_quiz)
        text += (
            "\n\nОтправьте ответы одним сообщением — "
            f"по одной строке на каждый вопрос ({len(questions)} шт.)."
        )
    elif step_type == "ack":
        markup = complete_step_keyboard(item.id, label="✅ Подтверждаю")
    else:
        label = "✅ Прочитано" if step_type == "content" else "✅ Выполнено"
        markup = complete_step_keyboard(item.id, label=label)
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.message(F.text == MENU_MY_ONBOARDING)
async def my_onboarding(message: Message, api: OnboardApiClient, state: FSMContext) -> None:
    if message.from_user is None:
        return

    try:
        employee = await api.find_employee_by_telegram(
            message.from_user.id,
            handler="my_onboarding",
            chat_id=message.chat.id if message.chat else None,
        )
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
        program = await api.get_program(assignment.program_id)
        progress = await api.get_progress(assignment.id)
        done = sum(1 for i in progress.items if i.status in _DONE_STATUSES)
        total = len(progress.items)
        remaining = max(0, total - done)
        current = api.first_incomplete_step(progress)
        step_title = (
            current[1].step.title
            if current and current[1].step is not None
            else "—"
        )
        overview = (
            f"📚 <b>Ваш онбординг</b>\n\n"
            f"Программа: {escape(program.title)}\n"
            f"Прогресс: {done} / {total}\n"
            f"{progress.percentage:.0f}%\n"
            f"Осталось: {remaining}\n\n"
            f"Текущий шаг:\n{escape(step_title)}"
        )
        await message.answer(overview)
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
        step_type = str(data.get("step_type") or "content")
        payload = {"ack": True} if step_type == "ack" else None
        await api.complete_progress(progress_id, payload=payload)
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


_MENU_TEXTS = frozenset(
    {
        MENU_MY_ONBOARDING,
        MENU_ACTIVE,
        MENU_HISTORY,
        MENU_CALENDAR,
        MENU_COMPANY,
        MENU_PROFILE,
    }
)


@router.message(
    OnboardingStates.answering_quiz,
    F.text,
    ~F.text.in_(_MENU_TEXTS),
)
async def quiz_answers(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    if message.from_user is None or not message.text:
        return

    data = await state.get_data()
    assignment_id_raw = data.get("assignment_id")
    program_id_raw = data.get("program_id")
    progress_id_raw = data.get("progress_id")
    if assignment_id_raw is None or program_id_raw is None or progress_id_raw is None:
        await message.answer("Сессия устарела. Откройте «Мой онбординг» снова.")
        return

    if not await api.ensure_session(message.from_user.id):
        await message.answer("Сессия устарела. Откройте «Мой онбординг» снова.")
        return

    try:
        progress = await api.get_progress(UUID(assignment_id_raw))
    except OnboardApiError:
        await message.answer("Не удалось загрузить шаг. Попробуйте позже.")
        return

    current = api.first_incomplete_step(progress)
    if current is None or str(current[1].id) != str(progress_id_raw):
        await message.answer("Этот шаг уже неактуален. Откройте «Мой онбординг» снова.")
        return

    item = current[1]
    questions = parse_questions(item.step.content if item.step else None)
    lines = [line.strip() for line in message.text.splitlines() if line.strip()]
    if len(lines) != len(questions):
        await message.answer(
            f"Нужно {len(questions)} ответ(а/ов) — по одному на строку. "
            "Отправьте сообщение ещё раз."
        )
        return

    answers = {question["id"]: answer for question, answer in zip(questions, lines, strict=True)}
    try:
        completed = await api.complete_progress(item.id, payload={"answers": answers})
    except OnboardApiError as exc:
        if exc.status_code == 409:
            await message.answer("Шаг уже выполнен.")
            return
        else:
            await message.answer("Не удалось сохранить ответы. Попробуйте ещё раз.")
            return

    quiz_score = completed.payload.get("quiz_score") if completed.payload else None
    if isinstance(quiz_score, dict):
        correct = quiz_score.get("correct_count")
        total = quiz_score.get("total")
        if correct is not None and total is not None:
            handled = False
            update_id = api.current_telegram_update_id()
            if isinstance(update_id, int) and not isinstance(update_id, bool):
                handled = await TelegramOutboundExecutor(
                    message.bot,
                    api,
                ).deliver_source(
                    source_type="quiz_result",
                    source_key=str(item.id),
                )
            if not handled:
                await message.answer(f"Результат теста: {correct} из {total}.")

    try:
        await _show_current_step(
            message=message,
            api=api,
            state=state,
            assignment_id=UUID(assignment_id_raw),
            program_id=UUID(program_id_raw),
        )
    except OnboardApiError:
        await message.answer(
            "Ответы сохранены, но не удалось открыть следующий шаг. "
            "Откройте «Мой онбординг» снова."
        )
