from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

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
from app.bot.keyboards.onboarding import (
    complete_step_keyboard,
    parse_complete_callback,
    parse_quiz_confirm_callback,
    parse_quiz_select_callback,
    quiz_options_keyboard,
)
from app.bot.services.outbound_delivery import TelegramOutboundExecutor
from app.bot.states.onboarding import OnboardingStates
from app.services.assessment import (
    format_quiz_result_message,
    is_structured_quiz,
    public_structured_questions,
)
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
    footer: str | None = None,
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
        footer=footer,
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
    quiz_content = item.step.content if item.step is not None else None
    structured_questions = (
        public_structured_questions(quiz_content)
        if step_type == "quiz" and is_structured_quiz(quiz_content)
        else []
    )
    footer = None
    if structured_questions:
        footer = "Ответьте на вопросы с помощью кнопок."
    text = _format_step_message(
        program_title=program.title,
        percentage=progress.percentage,
        step_number=step_number,
        total_steps=len(progress.items),
        item=item,
        footer=footer,
    )
    markup = None
    if structured_questions:
        await state.set_state(OnboardingStates.answering_structured_quiz)
        await state.update_data(
            quiz_q_index=0,
            quiz_answers={},
            quiz_toggles=[],
        )
        text, markup = _structured_question_view(text, structured_questions, 0, set())
    elif step_type == "quiz":
        questions = parse_questions(quiz_content)
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


def _structured_question_view(
    intro: str,
    questions: list[dict],
    index: int,
    selected: set[str],
) -> tuple[str, InlineKeyboardMarkup]:
    question = questions[index]
    total = len(questions)
    qtype = str(question.get("type") or "single_choice")
    options = question.get("options") if isinstance(question.get("options"), list) else []
    prompt = (
        "Выберите один или несколько вариантов и нажмите «Подтвердить ответ»."
        if qtype == "multiple_choice"
        else "Выберите один вариант."
    )
    text = (
        f"{intro}\n\n"
        f"<b>Вопрос {index + 1} из {total}</b>\n"
        f"{escape(str(question.get('text') or ''))}\n\n"
        f"{prompt}"
    )
    markup = quiz_options_keyboard(
        index,
        options if isinstance(options, list) else [],
        multiple=qtype == "multiple_choice",
        selected=selected,
    )
    return text, markup


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


@router.message(
    OnboardingStates.answering_structured_quiz,
    F.text,
    ~F.text.in_(_MENU_TEXTS),
)
async def structured_quiz_text(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    del api, state
    await message.answer("Выберите ответ кнопками под вопросом.")


@router.callback_query(
    OnboardingStates.answering_structured_quiz,
    F.data.startswith("qsel:"),
)
async def structured_quiz_select(
    callback: CallbackQuery,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    parsed = parse_quiz_select_callback(callback.data)
    if parsed is None:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    question_index, option_id = parsed
    context = await _structured_quiz_context(callback, api, state)
    if context is None:
        return
    questions, intro, item = context
    if question_index < 0 or question_index >= len(questions):
        await callback.answer("Этот вопрос уже неактуален", show_alert=True)
        return
    question = questions[question_index]
    qtype = str(question.get("type") or "single_choice")
    data = await state.get_data()
    if int(data.get("quiz_q_index") or 0) != question_index:
        await callback.answer("Сначала ответьте на текущий вопрос", show_alert=True)
        return

    if qtype == "multiple_choice":
        toggles = {str(value) for value in (data.get("quiz_toggles") or [])}
        if option_id in toggles:
            toggles.remove(option_id)
        else:
            toggles.add(option_id)
        await state.update_data(quiz_toggles=sorted(toggles))
        text, markup = _structured_question_view(intro, questions, question_index, toggles)
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()
        return

    answers = dict(data.get("quiz_answers") or {})
    answers[str(question.get("id"))] = [option_id]
    await state.update_data(quiz_answers=answers, quiz_toggles=[])
    await callback.answer()
    await _advance_structured_quiz(
        callback,
        api,
        state,
        questions=questions,
        intro=intro,
        item=item,
        answers=answers,
        question_index=question_index,
    )


@router.callback_query(
    OnboardingStates.answering_structured_quiz,
    F.data.startswith("qok:"),
)
async def structured_quiz_confirm(
    callback: CallbackQuery,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    question_index = parse_quiz_confirm_callback(callback.data)
    if question_index is None:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    context = await _structured_quiz_context(callback, api, state)
    if context is None:
        return
    questions, intro, item = context
    data = await state.get_data()
    if int(data.get("quiz_q_index") or 0) != question_index:
        await callback.answer("Сначала ответьте на текущий вопрос", show_alert=True)
        return
    toggles = [str(value) for value in (data.get("quiz_toggles") or [])]
    if not toggles:
        await callback.answer("Выберите хотя бы один вариант", show_alert=True)
        return
    question = questions[question_index]
    answers = dict(data.get("quiz_answers") or {})
    answers[str(question.get("id"))] = toggles
    await state.update_data(quiz_answers=answers, quiz_toggles=[])
    await callback.answer()
    await _advance_structured_quiz(
        callback,
        api,
        state,
        questions=questions,
        intro=intro,
        item=item,
        answers=answers,
        question_index=question_index,
    )


async def _structured_quiz_context(
    callback: CallbackQuery,
    api: OnboardApiClient,
    state: FSMContext,
) -> tuple[list[dict], str, ProgressItemDTO] | None:
    if callback.message is None:
        await callback.answer()
        return None
    data = await state.get_data()
    assignment_id_raw = data.get("assignment_id")
    program_id_raw = data.get("program_id")
    progress_id_raw = data.get("progress_id")
    telegram_user_id = data.get("telegram_user_id")
    if assignment_id_raw is None or program_id_raw is None or progress_id_raw is None:
        await callback.answer(
            "Сессия устарела. Откройте «Мой онбординг» снова.",
            show_alert=True,
        )
        return None
    user_id = telegram_user_id or (
        callback.from_user.id if callback.from_user is not None else None
    )
    if user_id is None or not await api.ensure_session(int(user_id)):
        await callback.answer(
            "Сессия устарела. Откройте «Мой онбординг» снова.",
            show_alert=True,
        )
        return None
    try:
        program = await api.get_program(UUID(program_id_raw))
        progress = await api.get_progress(UUID(assignment_id_raw))
    except OnboardApiError:
        await callback.answer("Не удалось загрузить шаг", show_alert=True)
        return None
    current = api.first_incomplete_step(progress)
    if current is None or str(current[1].id) != str(progress_id_raw):
        await callback.answer("Этот шаг уже неактуален", show_alert=True)
        return None
    item = current[1]
    questions = public_structured_questions(
        item.step.content if item.step is not None else None
    )
    if not questions:
        await callback.answer("Тест недоступен", show_alert=True)
        return None
    step_number, _ = current
    intro = _format_step_message(
        program_title=program.title,
        percentage=progress.percentage,
        step_number=step_number,
        total_steps=len(progress.items),
        item=item,
        footer="Ответьте на вопросы с помощью кнопок.",
    )
    return questions, intro, item


async def _advance_structured_quiz(
    callback: CallbackQuery,
    api: OnboardApiClient,
    state: FSMContext,
    *,
    questions: list[dict],
    intro: str,
    item: ProgressItemDTO,
    answers: dict,
    question_index: int,
) -> None:
    if callback.message is None:
        return
    next_index = question_index + 1
    if next_index < len(questions):
        await state.update_data(quiz_q_index=next_index, quiz_toggles=[])
        text, markup = _structured_question_view(intro, questions, next_index, set())
        await callback.message.edit_text(text, reply_markup=markup)
        return

    payload_answers = [
        {
            "question_id": question["id"],
            "selected_option_ids": list(answers.get(str(question["id"])) or []),
        }
        for question in questions
    ]
    try:
        completed = await api.complete_progress(
            item.id,
            payload={"answers": payload_answers},
        )
    except OnboardApiError as exc:
        if exc.status_code == 409:
            await callback.message.edit_text("Шаг уже выполнен.")
            return
        await callback.message.edit_text("Не удалось сохранить ответы. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    assignment_id_raw = data.get("assignment_id")
    program_id_raw = data.get("program_id")
    await _announce_structured_result(callback, api, completed, item)
    if assignment_id_raw is None or program_id_raw is None:
        return
    try:
        await _show_current_step(
            message=callback.message,
            api=api,
            state=state,
            assignment_id=UUID(assignment_id_raw),
            program_id=UUID(program_id_raw),
        )
    except OnboardApiError:
        await callback.message.answer(
            "Ответы сохранены, но не удалось открыть следующий шаг. "
            "Откройте «Мой онбординг» снова."
        )


async def _announce_structured_result(
    callback: CallbackQuery,
    api: OnboardApiClient,
    completed: ProgressItemDTO,
    item: ProgressItemDTO,
) -> None:
    if callback.message is None:
        return
    payload = completed.payload if isinstance(completed.payload, dict) else {}
    score = payload.get("last_score")
    if not isinstance(score, int):
        quiz_score = payload.get("quiz_score")
        if isinstance(quiz_score, dict) and isinstance(quiz_score.get("score"), int):
            score = quiz_score["score"]
        else:
            score = 0
    passed = bool(payload.get("passed"))
    passing = 80
    quiz_score = payload.get("quiz_score")
    if isinstance(quiz_score, dict) and isinstance(quiz_score.get("passing_score"), int):
        passing = quiz_score["passing_score"]
    body = format_quiz_result_message(score=score, passed=passed, passing_score=passing)
    handled = False
    update_id = api.current_telegram_update_id()
    attempt_count = payload.get("attempt_count")
    if (
        isinstance(update_id, int)
        and not isinstance(update_id, bool)
        and isinstance(attempt_count, int)
    ):
        handled = await TelegramOutboundExecutor(callback.message.bot, api).deliver_source(
            source_type="quiz_result",
            source_key=f"{item.id}:a{attempt_count}",
        )
    if not handled:
        await callback.message.answer(body)
