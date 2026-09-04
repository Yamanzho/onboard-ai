"""Telegram employee cabinet: Active / History / Calendar / Company / Profile."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.api.schemas import EmployeeDTO
from app.bot.keyboards.menu import (
    MENU_ACTIVE,
    MENU_CALENDAR,
    MENU_COMPANY,
    MENU_HISTORY,
    MENU_PROFILE,
)
from app.bot.keyboards.onboarding import assignment_open_keyboard
from app.db.assignment_rules import assignment_sort_key

router = Router(name="cabinet")


def _fmt_date(value: datetime | date | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%d.%m.%Y")
    return value.strftime("%d.%m.%Y")


async def _require_employee(
    message: Message,
    api: OnboardApiClient,
    *,
    handler: str,
) -> EmployeeDTO | None:
    if message.from_user is None:
        return None
    try:
        employee = await api.find_employee_by_telegram(
            message.from_user.id,
            handler=handler,
            chat_id=message.chat.id if message.chat else None,
        )
    except OnboardApiError:
        await message.answer("Не удалось связаться с сервером. Попробуйте позже.")
        return None
    if employee is None:
        await message.answer(
            "Вы ещё не добавлены в OnboardAI.\n"
            "Обратитесь к HR, чтобы вас зарегистрировали."
        )
        return None
    if employee.status == "archived":
        await message.answer("Ваш аккаунт архивирован. Обратитесь к HR.")
        return None
    return employee


@router.message(F.text == MENU_ACTIVE)
async def active_assignments(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    employee = await _require_employee(message, api, handler="active_assignments")
    if employee is None:
        return
    await state.clear()

    try:
        in_progress = await api.list_assignments(employee.id, status="in_progress")
        pending = await api.list_assignments(employee.id, status="pending")
    except OnboardApiError:
        await message.answer("Не удалось загрузить назначения. Попробуйте позже.")
        return

    items = sorted(
        [*in_progress, *pending],
        key=lambda a: assignment_sort_key(
            priority=a.priority,
            due_at=a.due_at,
            status=a.status,
            assigned_at=a.assigned_at,
        ),
    )
    if not items:
        await message.answer("🔥 Активные\n\nАктивных назначений нет.")
        return

    lines = ["🔥 <b>Активные</b>\n"]
    buttons: list[tuple[UUID, str]] = []
    for assignment in items:
        try:
            program = await api.get_program(assignment.program_id)
            progress = await api.get_progress(assignment.id)
            title = program.title
            pct = f"{progress.percentage:.0f}%"
            current = api.first_incomplete_step(progress)
            step_title = (
                current[1].step.title
                if current and current[1].step is not None
                else "—"
            )
        except OnboardApiError:
            title = str(assignment.program_id)
            pct = "—"
            step_title = "—"

        buttons.append((assignment.id, title))
        block = (
            f"<b>{escape(title)}</b>\n"
            f"Прогресс: {pct}\n"
            f"Начало: {_fmt_date(assignment.started_at or assignment.assigned_at)}\n"
            f"Текущий шаг: {escape(step_title)}"
        )
        if assignment.due_at is not None:
            block += f"\nСрок: {_fmt_date(assignment.due_at)}"
        lines.append(block)

    await message.answer(
        "\n\n".join(lines),
        reply_markup=assignment_open_keyboard(buttons) if buttons else None,
    )


@router.message(F.text == MENU_HISTORY)
async def history_assignments(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    employee = await _require_employee(message, api, handler="history_assignments")
    if employee is None:
        return
    await state.clear()

    try:
        completed = await api.list_assignments(employee.id, status="completed")
    except OnboardApiError:
        await message.answer("Не удалось загрузить историю. Попробуйте позже.")
        return

    if not completed:
        await message.answer("📜 История\n\nИстория пока пуста.")
        return

    lines = ["📜 <b>История</b>\n"]
    for assignment in sorted(
        completed,
        key=lambda a: a.completed_at or a.assigned_at,
        reverse=True,
    ):
        try:
            program = await api.get_program(assignment.program_id)
            progress = await api.get_progress(assignment.id)
            title = program.title
            done = sum(
                1
                for i in progress.items
                if i.status in {"completed", "skipped"}
            )
            total = len(progress.items)
            steps = f"{done}/{total} шагов"
        except OnboardApiError:
            title = str(assignment.program_id)
            steps = "—"

        lines.append(
            f"<b>{escape(title)}</b>\n"
            f"Завершено: {_fmt_date(assignment.completed_at)}\n"
            f"{steps}"
        )

    await message.answer("\n\n".join(lines))


def _bucket_label(when: datetime, now: datetime) -> str | None:
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    day = when.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if day == start:
        return "Сегодня"
    if day == start + timedelta(days=1):
        return "Завтра"
    if start < day < start + timedelta(days=7):
        return "Следующая неделя"
    return None


@router.message(F.text == MENU_CALENDAR)
async def calendar_view(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    employee = await _require_employee(message, api, handler="calendar_view")
    if employee is None:
        return
    await state.clear()

    try:
        assignments = await api.list_assignments(employee.id)
    except OnboardApiError:
        await message.answer("Не удалось загрузить календарь. Попробуйте позже.")
        return

    now = datetime.now(UTC)
    buckets: dict[str, list[str]] = {
        "Сегодня": [],
        "Завтра": [],
        "Следующая неделя": [],
    }

    for assignment in assignments:
        try:
            program = await api.get_program(assignment.program_id)
            title = program.title
        except OnboardApiError:
            title = "Программа"

        events: list[tuple[datetime, str]] = []
        if assignment.assigned_at:
            events.append((assignment.assigned_at, f"Начало: {title}"))
        if assignment.due_at:
            events.append((assignment.due_at, f"Дедлайн: {title}"))
        if assignment.completed_at:
            events.append((assignment.completed_at, f"Завершено: {title}"))

        for when, label in events:
            bucket = _bucket_label(when, now)
            if bucket is not None:
                buckets[bucket].append(escape(label))

    if not any(buckets.values()):
        await message.answer("📅 Календарь\n\nЗапланированных событий нет.")
        return

    lines = ["📅 <b>Календарь</b>"]
    for name in ("Сегодня", "Завтра", "Следующая неделя"):
        items = buckets[name]
        if not items:
            continue
        lines.append(f"\n<b>{name}:</b>")
        for item in items:
            lines.append(f"• {item}")

    await message.answer("\n".join(lines))


@router.message(F.text == MENU_COMPANY)
async def company_view(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    employee = await _require_employee(message, api, handler="company_view")
    if employee is None:
        return
    await state.clear()

    try:
        me = await api.get_me()
    except OnboardApiError:
        await message.answer("Не удалось загрузить данные компании.")
        return

    company = escape(me.company_name or "—")
    description = (me.company_description or "").strip()
    hired = _fmt_date(me.hired_at) if me.hired_at else "—"

    text = (
        "🏢 <b>Компания</b>\n\n"
        f"Компания:\n{company}\n"
    )
    if description:
        text += f"\nОписание:\n{escape(description)}\n"
    text += f"\nДата начала:\n{hired}"
    await message.answer(text)


@router.message(F.text == MENU_PROFILE)
async def profile_view(
    message: Message,
    api: OnboardApiClient,
    state: FSMContext,
) -> None:
    employee = await _require_employee(message, api, handler="profile_view")
    if employee is None:
        return
    await state.clear()

    try:
        me = await api.get_me()
    except OnboardApiError:
        await message.answer("Не удалось загрузить профиль.")
        return

    tg = "Connected" if me.telegram_connected else "Not connected"
    text = (
        "👤 <b>Мой профиль</b>\n\n"
        f"Имя: {escape(me.full_name)}\n"
        f"Email: {escape(me.email or '—')}\n"
        f"Компания: {escape(me.company_name or '—')}\n"
        f"Telegram: {tg}"
    )
    await message.answer(text)
