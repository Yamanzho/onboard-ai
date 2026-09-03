"""Render onboarding step content for Telegram messages."""

from __future__ import annotations

from html import escape
from typing import Any

from app.services.step_content import parse_questions
from app.services.telegram_format import (
    TELEGRAM_MAX_MESSAGE_LENGTH as TELEGRAM_MAX_MESSAGE_LENGTH,
)
from app.services.telegram_format import truncate_telegram_html


def render_step_content_body(content: dict[str, Any] | None) -> str:
    """Turn step.content JSONB into human-readable plain text (HTML-escaped later).

    Known keys: ``body``, ``text``, ``url``, ``link``.
    Unknown scalar string/number fields are appended as ``key: value``.
    Empty / non-dict content yields an empty string.
    """
    if not content or not isinstance(content, dict):
        return ""

    parts: list[str] = []
    consumed: set[str] = set()

    for key in ("body", "text"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
            consumed.add(key)

    for key in ("url", "link"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
            consumed.add(key)

    questions = parse_questions(content)
    if questions:
        consumed.add("questions")
        q_lines = ["Вопросы:"]
        for index, question in enumerate(questions, start=1):
            q_lines.append(f"{index}. {question['text']}")
        parts.append("\n".join(q_lines))

    for key, value in content.items():
        if key in consumed:
            continue
        if isinstance(value, bool):
            parts.append(f"{key}: {'yes' if value else 'no'}")
        elif isinstance(value, (str, int, float)) and str(value).strip():
            parts.append(f"{key}: {value}")
        # Nested objects / lists are intentionally skipped (unknown structure).

    return "\n\n".join(parts)


def format_step_message(
    *,
    program_title: str,
    percentage: float,
    step_number: int,
    total_steps: int,
    status_label: str,
    step_title: str | None,
    step_description: str | None,
    step_content: dict[str, Any] | None,
) -> str:
    """Build an HTML Telegram message for the current onboarding step."""
    lines: list[str] = [
        f"📚 <b>{escape(program_title)}</b>",
        f"Прогресс: {percentage:.0f}%",
        "",
        f"<b>Шаг {step_number} из {total_steps}</b>",
    ]

    if step_title and step_title.strip():
        lines.append(f"<b>{escape(step_title.strip())}</b>")

    lines.append(f"Статус: {escape(status_label)}")

    if step_description and step_description.strip():
        lines.extend(["", escape(step_description.strip())])

    body = render_step_content_body(step_content)
    if body:
        lines.extend(["", escape(body)])

    lines.extend(["", "Когда выполните шаг — нажмите кнопку ниже."])
    text = "\n".join(lines)
    return truncate_telegram_html(text)
