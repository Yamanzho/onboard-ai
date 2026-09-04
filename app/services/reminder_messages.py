"""Deterministic Telegram templates for assignment notifications."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape

from app.db.enums import AssignmentPriority
from app.services.notification_settings import resolve_timezone

_MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_PRIORITY_LABEL = {
    AssignmentPriority.IMPORTANT.value: "важный",
    AssignmentPriority.CRITICAL.value: "критичный",
}


def format_due_ru(due_at: datetime | None, timezone_name: str) -> str | None:
    if due_at is None:
        return None
    aware = due_at if due_at.tzinfo is not None else due_at.replace(tzinfo=UTC)
    local = aware.astimezone(resolve_timezone(timezone_name))
    return f"{local.day} {_MONTHS_RU[local.month - 1]}"


def format_initial_assignment_message(
    *,
    program_title: str,
    priority: str,
    due_at: datetime | None,
    timezone_name: str,
    overdue: bool = False,
) -> str:
    lines = [f"Вам назначен курс «{escape(program_title)}»."]
    label = _PRIORITY_LABEL.get(priority)
    if label:
        lines.append(f"Приоритет: {label}.")
    due = format_due_ru(due_at, timezone_name)
    if due:
        lines.append(f"Срок: {due}.")
    if overdue:
        lines.append("Срок уже прошёл.")
    return "\n".join(lines)


def format_reminder_message(
    *,
    program_title: str,
    priority: str,
    due_at: datetime | None,
    timezone_name: str,
    overdue: bool,
) -> str:
    title = escape(program_title)
    if priority == AssignmentPriority.CRITICAL.value:
        lead = f"Критично: необходимо завершить «{title}»."
    elif priority == AssignmentPriority.IMPORTANT.value:
        lead = f"Важно: курс «{title}» ещё не завершён."
    else:
        lead = f"Напоминание: у вас есть незавершённый курс «{title}»."
    lines = [lead]
    due = format_due_ru(due_at, timezone_name)
    if due:
        lines.append(f"Срок: {due}.")
    if overdue:
        lines.append("Срок уже прошёл.")
    return "\n".join(lines)
