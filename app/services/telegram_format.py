from __future__ import annotations

from html import escape
from typing import Any

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_SAFE_MESSAGE_LENGTH = 3900


def truncate_telegram_html(
    text: str,
    *,
    max_length: int = _SAFE_MESSAGE_LENGTH,
) -> str:
    """Truncate oversized messages without leaving a dangling open tag."""
    if len(text) <= max_length:
        return text
    cut = text[: max_length - 1]
    newline = cut.rfind("\n")
    if newline > max_length // 2:
        cut = cut[:newline]
    return f"{cut}…"


def format_ai_reply(payload: dict[str, Any]) -> str:
    """Render the public AI chat response into the persisted Telegram body."""
    answer = str(payload.get("answer") or "")
    no_answer = bool(payload.get("no_answer"))
    text = escape(answer)
    if no_answer:
        return truncate_telegram_html(text)

    titles: list[str] = []
    raw_citations = payload.get("citations") or []
    if isinstance(raw_citations, list):
        for item in raw_citations:
            title = ""
            if isinstance(item, dict):
                title = str(item.get("title") or "").strip()
            if title:
                titles.append(escape(title))
    if titles:
        bullets = "\n".join(f"• {title}" for title in titles)
        text = f"{text}\n\nИсточники:\n{bullets}"
    return truncate_telegram_html(text)
