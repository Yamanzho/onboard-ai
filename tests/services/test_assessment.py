"""Phase 9E: structured quiz definition, scoring, and attempt summaries."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.exceptions import ValidationError
from app.services.assessment import (
    PASSING_SCORE,
    apply_quiz_attempt,
    format_quiz_result_message,
    public_quiz_content,
    public_structured_questions,
    score_percentage,
    score_structured_quiz,
    validate_quiz_definition,
)


def _quiz(*questions: dict, passing_score: int = PASSING_SCORE) -> dict:
    return {"questions": list(questions), "passing_score": passing_score}


def _single(
    qid: str = "q1",
    *,
    text: str = "Capital?",
    correct: str = "b",
    options: list[tuple[str, str]] | None = None,
) -> dict:
    opts = options or [("a", "Almaty"), ("b", "Astana")]
    return {
        "id": qid,
        "type": "single_choice",
        "text": text,
        "options": [{"id": oid, "text": label} for oid, label in opts],
        "correct_option_ids": [correct],
    }


def _multi(
    qid: str = "q2",
    *,
    text: str = "Pick even",
    correct: list[str] | None = None,
    options: list[tuple[str, str]] | None = None,
) -> dict:
    opts = options or [("a", "2"), ("b", "3"), ("c", "4")]
    return {
        "id": qid,
        "type": "multiple_choice",
        "text": text,
        "options": [{"id": oid, "text": label} for oid, label in opts],
        "correct_option_ids": correct or ["a", "c"],
    }


def test_single_choice_valid() -> None:
    validate_quiz_definition(_quiz(_single()))


def test_single_choice_zero_correct_rejected() -> None:
    question = _single()
    question["correct_option_ids"] = []
    with pytest.raises(ValidationError, match="exactly one correct"):
        validate_quiz_definition(_quiz(question))


def test_single_choice_multiple_correct_rejected() -> None:
    question = _single()
    question["correct_option_ids"] = ["a", "b"]
    with pytest.raises(ValidationError, match="exactly one correct"):
        validate_quiz_definition(_quiz(question))


def test_multiple_choice_one_or_more_correct() -> None:
    validate_quiz_definition(_quiz(_multi(correct=["a"])))
    validate_quiz_definition(_quiz(_multi(correct=["a", "c"])))


def test_multiple_choice_zero_correct_rejected() -> None:
    question = _multi()
    question["correct_option_ids"] = []
    with pytest.raises(ValidationError, match="at least one correct"):
        validate_quiz_definition(_quiz(question))


def test_duplicate_question_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        validate_quiz_definition(_quiz(_single("q1"), _single("q1", text="Other")))


def test_duplicate_option_ids_rejected() -> None:
    question = _single(options=[("a", "One"), ("a", "Two")])
    with pytest.raises(ValidationError, match="option ids must be unique"):
        validate_quiz_definition(_quiz(question))


def test_unknown_correct_option_rejected() -> None:
    question = _single(correct="z")
    with pytest.raises(ValidationError, match="reference existing"):
        validate_quiz_definition(_quiz(question))


def test_fewer_than_two_options_rejected() -> None:
    question = _single(options=[("a", "Only")])
    with pytest.raises(ValidationError, match="at least 2 options"):
        validate_quiz_definition(_quiz(question))


def test_blank_question_and_option_rejected() -> None:
    with pytest.raises(ValidationError, match="question text"):
        validate_quiz_definition(_quiz(_single(text="  ")))
    with pytest.raises(ValidationError, match="option text"):
        validate_quiz_definition(_quiz(_single(options=[("a", ""), ("b", "B")])))


def test_unsupported_type_rejected() -> None:
    question = _single()
    question["type"] = "free_text"
    with pytest.raises(ValidationError, match="unsupported question type"):
        validate_quiz_definition(_quiz(question))


def test_mixed_legacy_and_structured_rejected() -> None:
    with pytest.raises(ValidationError, match="must not mix"):
        validate_quiz_definition(
            {
                "questions": [
                    _single(),
                    {"id": "q2", "text": "Legacy", "correct": "x"},
                ]
            }
        )


def test_passing_score_must_remain_80() -> None:
    with pytest.raises(ValidationError, match="passing_score must be 80"):
        validate_quiz_definition(_quiz(_single(), passing_score=70))


def test_score_rounding_and_threshold() -> None:
    assert score_percentage(4, 5) == 80
    assert score_percentage(3, 5) == 60
    assert score_percentage(3, 4) == 75
    assert score_percentage(7, 8) == 88
    five = _quiz(
        _single("q1"),
        _single("q2", text="2?"),
        _single("q3", text="3?"),
        _single("q4", text="4?"),
        _single("q5", text="5?"),
    )
    answers_80 = [
        {"question_id": f"q{i}", "selected_option_ids": ["b" if i < 5 else "a"]}
        for i in range(1, 6)
    ]
    result = score_structured_quiz(five, answers_80)
    assert result.score == 80
    assert result.passed is True

    answers_60 = [
        {"question_id": f"q{i}", "selected_option_ids": ["b" if i <= 3 else "a"]}
        for i in range(1, 6)
    ]
    failed = score_structured_quiz(five, answers_60)
    assert failed.score == 60
    assert failed.passed is False

    four = _quiz(_single("q1"), _single("q2"), _single("q3"), _single("q4"))
    three_of_four = [
        {"question_id": f"q{i}", "selected_option_ids": ["b" if i < 4 else "a"]}
        for i in range(1, 5)
    ]
    assert score_structured_quiz(four, three_of_four).score == 75
    assert score_structured_quiz(four, three_of_four).passed is False

    eight = _quiz(*[_single(f"q{i}", text=str(i)) for i in range(1, 9)])
    seven = [
        {"question_id": f"q{i}", "selected_option_ids": ["b" if i < 8 else "a"]}
        for i in range(1, 9)
    ]
    rounded = score_structured_quiz(eight, seven)
    assert rounded.score == 88
    assert rounded.passed is True


def test_exact_set_scoring() -> None:
    content = _quiz(_single(), _multi())
    perfect = score_structured_quiz(
        content,
        [
            {"question_id": "q1", "selected_option_ids": ["b"]},
            {"question_id": "q2", "selected_option_ids": ["a", "c"]},
        ],
    )
    assert perfect.correct_count == 2
    assert perfect.passed is True

    partial = score_structured_quiz(
        content,
        [
            {"question_id": "q1", "selected_option_ids": ["b"]},
            {"question_id": "q2", "selected_option_ids": ["a"]},
        ],
    )
    assert partial.correct_count == 1
    extra = score_structured_quiz(
        content,
        [
            {"question_id": "q1", "selected_option_ids": ["b"]},
            {"question_id": "q2", "selected_option_ids": ["a", "b", "c"]},
        ],
    )
    assert extra.correct_count == 1


def test_answer_validation_rejects_malformed() -> None:
    content = _quiz(_single(), _multi())
    with pytest.raises(ValidationError, match="duplicate answers"):
        score_structured_quiz(
            content,
            [
                {"question_id": "q1", "selected_option_ids": ["b"]},
                {"question_id": "q1", "selected_option_ids": ["a"]},
                {"question_id": "q2", "selected_option_ids": ["a"]},
            ],
        )
    with pytest.raises(ValidationError, match="all questions"):
        score_structured_quiz(
            content,
            [{"question_id": "q1", "selected_option_ids": ["b"]}],
        )
    with pytest.raises(ValidationError, match="unknown question_id"):
        score_structured_quiz(
            content,
            [
                {"question_id": "q1", "selected_option_ids": ["b"]},
                {"question_id": "q9", "selected_option_ids": ["a"]},
            ],
        )
    with pytest.raises(ValidationError, match="unknown option"):
        score_structured_quiz(
            content,
            [
                {"question_id": "q1", "selected_option_ids": ["z"]},
                {"question_id": "q2", "selected_option_ids": ["a"]},
            ],
        )


def test_apply_quiz_attempt_accumulates() -> None:
    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    first = apply_quiz_attempt(
        {},
        score_structured_quiz(
            _quiz(_single("q1"), _single("q2")),
            [
                {"question_id": "q1", "selected_option_ids": ["a"]},
                {"question_id": "q2", "selected_option_ids": ["a"]},
            ],
        ),
        now=now,
    )
    assert first["attempt_count"] == 1
    assert first["best_score"] == 0
    assert first["passed"] is False
    second = apply_quiz_attempt(
        first,
        score_structured_quiz(
            _quiz(_single("q1"), _single("q2")),
            [
                {"question_id": "q1", "selected_option_ids": ["b"]},
                {"question_id": "q2", "selected_option_ids": ["b"]},
            ],
        ),
        now=now,
    )
    assert second["attempt_count"] == 2
    assert second["best_score"] == 100
    assert second["passed"] is True
    assert "answers" not in second


def test_public_quiz_content_strips_keys() -> None:
    cleaned = public_quiz_content(_quiz(_single(), _multi()))
    dumped = str(cleaned)
    assert "correct_option_ids" not in dumped
    assert "correct" not in dumped
    display = public_structured_questions(cleaned)
    assert display[0]["id"] == "q1"
    assert display[0]["options"][0]["id"] == "a"
    assert "correct_option_ids" not in display[0]


def test_result_message_is_not_punitive() -> None:
    assert format_quiz_result_message(score=85, passed=True) == (
        "Результат: 85%. Тест пройден."
    )
    assert "ещё раз" in format_quiz_result_message(score=70, passed=False)
    assert "минимум 80%" in format_quiz_result_message(score=70, passed=False)
