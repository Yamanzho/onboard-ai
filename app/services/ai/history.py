"""Bounded conversation history for LLM context. Not KB and not ACL."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.ai_constants import MAX_CHAT_HISTORY_CHARS, MAX_CHAT_HISTORY_MESSAGES
from app.core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    """One prior user or assistant turn. Content is untrusted DATA."""

    role: str
    content: str


def select_history_for_llm(
    turns: Sequence[HistoryTurn],
    *,
    max_messages: int = MAX_CHAT_HISTORY_MESSAGES,
    max_chars: int = MAX_CHAT_HISTORY_CHARS,
) -> tuple[HistoryTurn, ...]:
    """Keep the newest whole messages within count and character budgets.

    ``turns`` must already be chronological (oldest first). Older turns are
    dropped first. Messages are never split, so UTF-8 code points stay intact.
    A single turn longer than ``max_chars`` is skipped rather than truncated.
    """
    if max_messages < 1:
        raise ValidationError("max_messages must be an integer >= 1")
    if max_chars < 1:
        raise ValidationError("max_chars must be an integer >= 1")
    if not turns:
        return ()

    recent = list(turns)[-max_messages:]
    selected: list[HistoryTurn] = []
    total = 0
    for turn in reversed(recent):
        size = len(turn.content)
        if size > max_chars:
            continue
        if selected and total + size > max_chars:
            break
        selected.append(turn)
        total += size
    selected.reverse()
    return tuple(selected)
