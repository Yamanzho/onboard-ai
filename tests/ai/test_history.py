"""Bounded history helper: count, chars, chronology, whole UTF-8 messages."""

from __future__ import annotations

import pytest

from app.core.ai_constants import MAX_CHAT_HISTORY_CHARS, MAX_CHAT_HISTORY_MESSAGES
from app.core.exceptions import ValidationError
from app.services.ai.history import HistoryTurn, select_history_for_llm


def _turns(*contents: str, role: str = "user") -> tuple[HistoryTurn, ...]:
    return tuple(HistoryTurn(role=role, content=content) for content in contents)


def test_empty_history() -> None:
    assert select_history_for_llm(()) == ()


def test_max_message_count_keeps_newest() -> None:
    turns = _turns(*[f"m{i}" for i in range(15)])
    selected = select_history_for_llm(turns, max_messages=10, max_chars=12_000)
    assert len(selected) == MAX_CHAT_HISTORY_MESSAGES
    assert [turn.content for turn in selected] == [f"m{i}" for i in range(5, 15)]


def test_history_stays_chronological() -> None:
    turns = _turns("oldest", "middle", "newest")
    selected = select_history_for_llm(turns, max_messages=10, max_chars=12_000)
    assert [turn.content for turn in selected] == ["oldest", "middle", "newest"]


def test_char_limit_drops_oldest_whole_messages() -> None:
    turns = _turns(*["x" * 3000 for _ in range(5)])
    selected = select_history_for_llm(turns, max_messages=10, max_chars=12_000)
    assert len(selected) == 4
    assert all(len(turn.content) == 3000 for turn in selected)
    assert sum(len(turn.content) for turn in selected) == 12_000
    assert selected[0].content == turns[1].content
    assert selected[-1].content == turns[-1].content


def test_char_limit_does_not_split_utf8_code_points() -> None:
    snowman = "☃" * 5000
    newest = "ok"
    selected = select_history_for_llm(
        _turns(snowman, newest),
        max_messages=10,
        max_chars=12_000,
    )
    assert [turn.content for turn in selected] == [snowman, newest]
    assert selected[0].content == snowman


def test_single_oversized_message_is_skipped_not_truncated() -> None:
    huge = "y" * 12_001
    kept = "kept"
    selected = select_history_for_llm(
        _turns(kept, huge),
        max_messages=10,
        max_chars=12_000,
    )
    assert [turn.content for turn in selected] == [kept]
    assert huge not in {turn.content for turn in selected}


def test_default_limits_match_constants() -> None:
    turns = _turns(*[f"{i}" for i in range(12)])
    selected = select_history_for_llm(turns)
    assert len(selected) == MAX_CHAT_HISTORY_MESSAGES
    assert sum(len(turn.content) for turn in selected) <= MAX_CHAT_HISTORY_CHARS


def test_invalid_budgets_rejected() -> None:
    with pytest.raises(ValidationError, match="max_messages"):
        select_history_for_llm(_turns("a"), max_messages=0)
    with pytest.raises(ValidationError, match="max_chars"):
        select_history_for_llm(_turns("a"), max_chars=0)
