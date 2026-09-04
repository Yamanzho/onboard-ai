"""Deterministic Russian assistant copy. Not an electronic signature product."""

from __future__ import annotations

from datetime import datetime
from html import escape

from app.db.assignment_rules import is_assignment_overdue
from app.db.enums import AssignmentPriority
from app.services.reminder_messages import format_due_ru

GREETING_TEXT = "Здравствуйте! Чем могу помочь?"
THANKS_TEXT = "Пожалуйста. Если появится вопрос — напишите."
HELP_TEXT = (
    "Я могу:\n"
    "• отвечать на вопросы по компании\n"
    "• показывать ваши задания\n"
    "• помогать проходить обучение\n"
    "• подсказывать, к кому обратиться"
)
UNKNOWN_TEXT = (
    "Я могу помочь с вопросами по компании, заданиями, обучением "
    "или подсказать ответственного."
)
NO_ACTIVE_ASSIGNMENTS = "Сейчас у вас нет активных заданий."
NO_ACTIVE_COURSES = "Сейчас нет активного курса для продолжения."
NO_TRAINING_CONTEXT = (
    "Сейчас нет активного урока. Напишите «продолжи обучение», чтобы открыть курс."
)
RESPONSIBILITY_UNCONFIGURED = (
    "Для этой темы ответственный в OnboardAI пока не настроен."
)
RESPONSIBILITY_UNKNOWN_TOPIC = (
    "Не удалось определить тему. Уточните, пожалуйста, например: "
    "отпуск, ноутбуки, зарплата."
)
NO_ANSWER_NO_OWNER = (
    "Надёжный ответ в базе знаний не найден, и ответственный по этой теме "
    "пока не настроен."
)
CONTINUE_ONE = "Продолжаем обучение."
CONTINUE_MANY = "У вас несколько активных курсов. Выберите, какой открыть:"
CONTINUE_NONE = (
    "Сейчас нет активного курса. Откройте «Мой онбординг», "
    "если нужно ознакомиться с документами."
)

_PRIORITY_RU = {
    AssignmentPriority.CRITICAL.value: "критично",
    AssignmentPriority.IMPORTANT.value: "важно",
}


def format_assignment_line(
    *,
    index: int,
    title: str,
    priority: str,
    due_at: datetime | None,
    status: str,
    progress_label: str | None,
    timezone_name: str,
) -> str:
    parts = [f"{index}. {title}"]
    priority_label = _PRIORITY_RU.get(priority)
    if priority_label:
        parts.append(priority_label)
    due = format_due_ru(due_at, timezone_name)
    if due:
        prefix = "срок прошёл" if is_assignment_overdue(due_at, status) else "до"
        parts.append(f"{prefix} {due}")
    if progress_label:
        parts.append(progress_label)
    return " — ".join(parts)


def format_assignment_list(
    lines: list[str],
    *,
    heading: str | None = None,
) -> str:
    if not lines:
        return NO_ACTIVE_ASSIGNMENTS
    title = heading or f"У вас {len(lines)} активных задания:"
    if len(lines) == 1:
        title = heading or "Ваше активное задание:"
    return "\n".join([title, "", *lines])


def format_responsibility(
    *,
    topic_name: str,
    department_name: str | None,
    employee_full_name: str | None,
    employee_job_title: str | None,
) -> str:
    lines = [f"По теме «{escape(topic_name)}»:"]
    if employee_full_name:
        role = f", {escape(employee_job_title)}" if employee_job_title else ""
        lines.append(f"• {escape(employee_full_name)}{role}")
    if department_name:
        lines.append(f"• отдел: {escape(department_name)}")
    if len(lines) == 1:
        return RESPONSIBILITY_UNCONFIGURED
    lines.append("Напишите им напрямую — я не создаю заявки и не уведомляю коллег.")
    return "\n".join(lines)


def format_unconfigured_with_manager(manager_name: str, job_title: str | None) -> str:
    role = f", {job_title}" if job_title else ""
    return (
        f"{RESPONSIBILITY_UNCONFIGURED}\n"
        f"Вы можете обратиться к своему руководителю: {manager_name}{role}."
    )


def format_training_help(
    *,
    program_title: str,
    step_title: str,
    explanation: str,
) -> str:
    body = explanation.strip()
    return (
        f"Сейчас вы проходите: {program_title} → {step_title}\n\n"
        f"{body}\n\n"
        "Это объяснение по назначенному материалу. Прогресс не изменился."
    )


def company_timezone(timezone_name: str | None) -> str:
    raw = (timezone_name or "UTC").strip()
    return raw or "UTC"
