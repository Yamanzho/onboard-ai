"""Deterministic assessment engine for structured quiz steps.

Quiz definitions live in ``Step.content`` (or ``Assignment.structure_snapshot``).
Attempt summaries live in ``Progress.payload``. No standalone quiz tables.

Legacy free-text quizzes keep ``score_quiz()`` in ``step_content``. Structured
quizzes (``single_choice`` / ``multiple_choice``) are scored here.

Rounding: integer percent via ``round(correct / total * 100)`` (Python half-even).
Examples: 4/5 → 80 pass; 3/4 → 75 fail; 7/8 → 88 pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.exceptions import ValidationError

PASSING_SCORE = 80
SUPPORTED_QUESTION_TYPES = frozenset({"single_choice", "multiple_choice"})
ANSWER_KEY_FIELDS = frozenset({"correct", "answer", "correct_option_ids"})
_QUESTION_ID_MAX = 64
_OPTION_ID_MAX = 64
_QUESTION_TEXT_MAX = 500
_OPTION_TEXT_MAX = 500
_EXPLANATION_MAX = 1000
_MAX_QUESTIONS = 20
_MAX_OPTIONS = 12


@dataclass(frozen=True, slots=True)
class QuizOption:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class StructuredQuestion:
    id: str
    type: str
    text: str
    options: tuple[QuizOption, ...]
    correct_option_ids: frozenset[str]
    explanation: str | None = None


@dataclass(frozen=True, slots=True)
class StructuredQuiz:
    questions: tuple[StructuredQuestion, ...]
    passing_score: int = PASSING_SCORE


@dataclass(frozen=True, slots=True)
class QuizScoreResult:
    correct_count: int
    total: int
    score: int
    passed: bool
    passing_score: int


def is_structured_question(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    qtype = item.get("type")
    if isinstance(qtype, str) and qtype.strip():
        return True
    if isinstance(item.get("options"), list):
        return True
    if isinstance(item.get("correct_option_ids"), list):
        return True
    return False


def is_structured_quiz(content: dict[str, Any] | None) -> bool:
    raw = _raw_questions(content)
    return any(is_structured_question(item) for item in raw)


def is_legacy_quiz(content: dict[str, Any] | None) -> bool:
    raw = _raw_questions(content)
    if not raw:
        return False
    return not any(is_structured_question(item) for item in raw)


def public_quiz_content(content: dict[str, Any] | None) -> dict[str, Any]:
    """Strip answer keys (and explanations) from quiz content for employees."""
    if not isinstance(content, dict):
        return {}
    out = dict(content)
    raw = out.get("questions")
    if not isinstance(raw, list):
        return out
    cleaned: list[Any] = []
    for item in raw:
        if isinstance(item, dict):
            question = {
                k: v
                for k, v in item.items()
                if k not in ANSWER_KEY_FIELDS and k != "explanation"
            }
            cleaned.append(question)
        else:
            cleaned.append(item)
    out["questions"] = cleaned
    return out


def public_progress_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Employee-safe progress payload: summary only, no answers or per-question keys."""
    if not isinstance(payload, dict):
        return {}
    out = dict(payload)
    out.pop("answers", None)
    score = out.get("quiz_score")
    if isinstance(score, dict):
        out["quiz_score"] = {k: v for k, v in score.items() if k != "results"}
    return out


def validate_quiz_definition(content: dict[str, Any] | None) -> None:
    """Validate a structured quiz definition. Raises ``ValidationError``."""
    parse_structured_quiz(content)


def parse_structured_quiz(content: dict[str, Any] | None) -> StructuredQuiz:
    if not isinstance(content, dict):
        raise ValidationError("quiz content must be an object")
    raw = content.get("questions")
    if not isinstance(raw, list) or not raw:
        raise ValidationError("quiz steps require at least one question in content.questions")
    if len(raw) > _MAX_QUESTIONS:
        raise ValidationError(
            f"quiz steps cannot contain more than {_MAX_QUESTIONS} questions"
        )

    if not all(is_structured_question(item) for item in raw):
        raise ValidationError("quiz must not mix structured and legacy questions")

    passing_raw = content.get("passing_score", PASSING_SCORE)
    if passing_raw is None:
        passing_raw = PASSING_SCORE
    if not isinstance(passing_raw, int) or isinstance(passing_raw, bool):
        raise ValidationError("passing_score must be 80")
    if passing_raw != PASSING_SCORE:
        raise ValidationError("passing_score must be 80")

    questions: list[StructuredQuestion] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"questions[{index}] must be an object")
        question = _parse_structured_question(item, index)
        if question.id in seen_ids:
            raise ValidationError("quiz question ids must be unique")
        seen_ids.add(question.id)
        questions.append(question)
    return StructuredQuiz(questions=tuple(questions), passing_score=PASSING_SCORE)


def score_percentage(correct_count: int, total: int) -> int:
    """Integer percent. ``round(correct / total * 100)``; 7/8 → 88."""
    if total <= 0:
        return 0
    return round(correct_count / total * 100)


def score_structured_quiz(
    content: dict[str, Any] | None,
    answers: Any,
) -> QuizScoreResult:
    quiz = parse_structured_quiz(content)
    selected = validate_quiz_answers(quiz, answers)
    correct_count = 0
    for question in quiz.questions:
        chosen = selected[question.id]
        if chosen == question.correct_option_ids:
            correct_count += 1
    total = len(quiz.questions)
    score = score_percentage(correct_count, total)
    return QuizScoreResult(
        correct_count=correct_count,
        total=total,
        score=score,
        passed=score >= quiz.passing_score,
        passing_score=quiz.passing_score,
    )


def validate_quiz_answers(
    quiz: StructuredQuiz,
    answers: Any,
) -> dict[str, frozenset[str]]:
    if not isinstance(answers, list):
        raise ValidationError("structured quiz answers must be a list")

    known_ids = {question.id for question in quiz.questions}
    selected: dict[str, frozenset[str]] = {}
    for index, item in enumerate(answers):
        if not isinstance(item, dict):
            raise ValidationError(f"answers[{index}] must be an object")
        qid_raw = item.get("question_id")
        if not isinstance(qid_raw, str) or not qid_raw.strip():
            raise ValidationError(f"answers[{index}].question_id is required")
        qid = qid_raw.strip()
        if qid not in known_ids:
            raise ValidationError(f"unknown question_id: {qid}")
        if qid in selected:
            raise ValidationError(f"duplicate answers for question {qid}")
        raw_opts = item.get("selected_option_ids")
        if not isinstance(raw_opts, list):
            raise ValidationError(
                f"answers[{index}].selected_option_ids must be a list"
            )
        option_ids: list[str] = []
        for opt in raw_opts:
            if not isinstance(opt, str) or not opt.strip():
                raise ValidationError(
                    f"answers[{index}].selected_option_ids must be non-empty strings"
                )
            option_ids.append(opt.strip())
        if len(option_ids) != len(set(option_ids)):
            raise ValidationError(
                f"answers[{index}].selected_option_ids must not contain duplicates"
            )
        selected[qid] = frozenset(option_ids)

    missing = [question.id for question in quiz.questions if question.id not in selected]
    if missing:
        raise ValidationError(
            "quiz completion requires answers for all questions: " + ", ".join(missing)
        )

    by_id = {question.id: question for question in quiz.questions}
    for qid, chosen in selected.items():
        question = by_id[qid]
        option_ids = {opt.id for opt in question.options}
        unknown = chosen - option_ids
        if unknown:
            raise ValidationError(
                f"unknown option id for question {qid}: {sorted(unknown)[0]}"
            )
        if question.type == "single_choice" and len(chosen) != 1:
            raise ValidationError(
                f"single_choice question {qid} requires exactly one selected option"
            )
        if question.type == "multiple_choice" and len(chosen) < 1:
            raise ValidationError(
                f"multiple_choice question {qid} requires at least one selected option"
            )
    return selected


def apply_quiz_attempt(
    existing_payload: dict[str, Any] | None,
    result: QuizScoreResult,
    *,
    now: datetime,
) -> dict[str, Any]:
    prev = existing_payload if isinstance(existing_payload, dict) else {}
    prev_count = prev.get("attempt_count")
    attempt_count = (int(prev_count) if isinstance(prev_count, int) else 0) + 1
    prev_best = prev.get("best_score")
    best = (
        result.score
        if not isinstance(prev_best, int)
        else max(prev_best, result.score)
    )
    timestamp = now.isoformat().replace("+00:00", "Z")
    return {
        "attempt_count": attempt_count,
        "last_score": result.score,
        "best_score": best,
        "last_attempt_at": timestamp,
        "passed": result.passed,
        "quiz_score": {
            "correct_count": result.correct_count,
            "total": result.total,
            "score": result.score,
            "passed": result.passed,
            "passing_score": result.passing_score,
        },
    }


def format_quiz_result_message(
    *,
    score: int,
    passed: bool,
    passing_score: int = PASSING_SCORE,
) -> str:
    if passed:
        return f"Результат: {score}%. Тест пройден."
    return (
        f"Результат: {score}%. Нужно минимум {passing_score}%. "
        "Можно попробовать ещё раз."
    )


def public_structured_questions(
    content: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Employee/Telegram view: questions with options, no answer keys.

    Must work on sanitized employee payloads that omit ``correct_option_ids``.
    """
    raw = _raw_questions(content)
    if not raw or not any(is_structured_question(item) for item in raw):
        return []
    questions: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        text_raw = item.get("text")
        if not isinstance(text_raw, str) or not text_raw.strip():
            continue
        qtype_raw = item.get("type")
        qtype = (
            qtype_raw.strip()
            if isinstance(qtype_raw, str) and qtype_raw.strip() in SUPPORTED_QUESTION_TYPES
            else "single_choice"
        )
        qid_raw = item.get("id")
        qid = (
            str(qid_raw).strip()[:_QUESTION_ID_MAX]
            if qid_raw is not None and str(qid_raw).strip()
            else f"q{index + 1}"
        )
        options: list[dict[str, str]] = []
        options_raw = item.get("options")
        if isinstance(options_raw, list):
            for opt_index, opt in enumerate(options_raw):
                if not isinstance(opt, dict):
                    continue
                opt_text = opt.get("text")
                if not isinstance(opt_text, str) or not opt_text.strip():
                    continue
                oid_raw = opt.get("id")
                oid = (
                    str(oid_raw).strip()[:_OPTION_ID_MAX]
                    if oid_raw is not None and str(oid_raw).strip()
                    else chr(ord("a") + opt_index)
                )
                options.append({"id": oid, "text": opt_text.strip()})
        if len(options) < 2:
            continue
        questions.append(
            {"id": qid, "type": qtype, "text": text_raw.strip(), "options": options}
        )
    return questions


def _raw_questions(content: dict[str, Any] | None) -> list[Any]:
    if not isinstance(content, dict):
        return []
    raw = content.get("questions")
    if not isinstance(raw, list):
        return []
    return raw


def _parse_structured_question(item: dict[str, Any], index: int) -> StructuredQuestion:
    qtype_raw = item.get("type")
    if not isinstance(qtype_raw, str) or qtype_raw.strip() not in SUPPORTED_QUESTION_TYPES:
        raise ValidationError(
            f"unsupported question type: {qtype_raw!r}; "
            "allowed: single_choice, multiple_choice"
        )
    qtype = qtype_raw.strip()

    text_raw = item.get("text")
    if not isinstance(text_raw, str) or not text_raw.strip():
        raise ValidationError("question text must not be empty")
    text = text_raw.strip()
    if len(text) > _QUESTION_TEXT_MAX:
        raise ValidationError(
            f"question text exceeds {_QUESTION_TEXT_MAX} characters"
        )

    qid_raw = item.get("id")
    qid = (
        str(qid_raw).strip()[:_QUESTION_ID_MAX]
        if qid_raw is not None and str(qid_raw).strip()
        else f"q{index + 1}"
    )

    options_raw = item.get("options")
    if not isinstance(options_raw, list):
        raise ValidationError("question options must be a list")
    if len(options_raw) < 2:
        raise ValidationError("quiz questions require at least 2 options")
    if len(options_raw) > _MAX_OPTIONS:
        raise ValidationError(
            f"question cannot have more than {_MAX_OPTIONS} options"
        )

    options: list[QuizOption] = []
    seen_option_ids: set[str] = set()
    for opt_index, opt in enumerate(options_raw):
        if not isinstance(opt, dict):
            raise ValidationError("question options must be objects")
        oid_raw = opt.get("id")
        oid = (
            str(oid_raw).strip()[:_OPTION_ID_MAX]
            if oid_raw is not None and str(oid_raw).strip()
            else chr(ord("a") + opt_index)
        )
        if oid in seen_option_ids:
            raise ValidationError("question option ids must be unique")
        seen_option_ids.add(oid)
        opt_text_raw = opt.get("text")
        if not isinstance(opt_text_raw, str) or not opt_text_raw.strip():
            raise ValidationError("option text must not be empty")
        opt_text = opt_text_raw.strip()
        if len(opt_text) > _OPTION_TEXT_MAX:
            raise ValidationError(
                f"option text exceeds {_OPTION_TEXT_MAX} characters"
            )
        options.append(QuizOption(id=oid, text=opt_text))

    correct_raw = item.get("correct_option_ids")
    if not isinstance(correct_raw, list) or not correct_raw:
        if qtype == "single_choice":
            raise ValidationError(
                "single_choice questions require exactly one correct option"
            )
        raise ValidationError(
            "multiple_choice questions require at least one correct option"
        )
    correct_ids: list[str] = []
    for cid in correct_raw:
        if not isinstance(cid, str) or not cid.strip():
            raise ValidationError("correct_option_ids must be non-empty strings")
        correct_ids.append(cid.strip())
    if len(correct_ids) != len(set(correct_ids)):
        raise ValidationError("correct_option_ids must not contain duplicates")
    option_ids = {opt.id for opt in options}
    unknown = [cid for cid in correct_ids if cid not in option_ids]
    if unknown:
        raise ValidationError("correct_option_ids must reference existing options")
    if qtype == "single_choice" and len(set(correct_ids)) != 1:
        raise ValidationError(
            "single_choice questions require exactly one correct option"
        )

    explanation = None
    expl_raw = item.get("explanation")
    if expl_raw is not None:
        if not isinstance(expl_raw, str):
            raise ValidationError("explanation must be a string when set")
        explanation = expl_raw.strip()[:_EXPLANATION_MAX] or None

    if "correct" in item or "answer" in item:
        raise ValidationError("quiz must not mix structured and legacy questions")

    return StructuredQuestion(
        id=qid,
        type=qtype,
        text=text,
        options=tuple(options),
        correct_option_ids=frozenset(correct_ids),
        explanation=explanation,
    )
