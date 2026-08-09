"""Render onboarding step content for Telegram messages."""

from __future__ import annotations

from html import escape
from typing import Any

# Telegram Bot API hard limit for message text.
_TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_SAFE_MESSAGE_LENGTH = 3900


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


def truncate_telegram_html(text: str, *, max_length: int = _SAFE_MESSAGE_LENGTH) -> str:
    """Truncate oversized messages without leaving a dangling open tag."""
    if len(text) <= max_length:
        return text
    # Prefer cutting on a newline boundary when possible.
    cut = text[: max_length - 1]
    nl = cut.rfind("\n")
    if nl > max_length // 2:
        cut = cut[:nl]
    return f"{cut}…"


# Keep constant export for tests.
TELEGRAM_MAX_MESSAGE_LENGTH = _TELEGRAM_MAX_MESSAGE_LENGTH
