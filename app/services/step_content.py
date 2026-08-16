"""Parse onboarding step.content JSONB and validate completion payloads."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ValidationError
from app.db.enums import StepType

_QUESTION_ID_MAX = 64
_QUESTION_TEXT_MAX = 500
_MAX_QUESTIONS = 20
_ANSWER_MAX = 2000
_URL_MAX = 2048
_CORRECT_MAX = 500


def parse_questions(content: dict[str, Any] | None) -> list[dict[str, str]]:
    """Return normalized quiz questions from ``content.questions``.

    Each item is ``{"id": str, "text": str}``. Unknown shapes are skipped.
    """
    if not content or not isinstance(content, dict):
        return []
    raw = content.get("questions")
    if not isinstance(raw, list):
        return []
    questions: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if len(questions) >= _MAX_QUESTIONS:
            break
        if isinstance(item, str) and item.strip():
            text = item.strip()[:_QUESTION_TEXT_MAX]
            questions.append({"id": f"q{index + 1}", "text": text})
            continue
        if not isinstance(item, dict):
            continue
        text_raw = item.get("text") or item.get("prompt") or item.get("question")
        if not isinstance(text_raw, str) or not text_raw.strip():
            continue
        qid_raw = item.get("id")
        qid = (
            str(qid_raw).strip()[:_QUESTION_ID_MAX]
            if qid_raw is not None and str(qid_raw).strip()
            else f"q{index + 1}"
        )
        questions.append({"id": qid, "text": text_raw.strip()[:_QUESTION_TEXT_MAX]})
    return questions


def parse_answer_key(content: dict[str, Any] | None) -> dict[str, str]:
    """Map question id → normalized correct answer. Questions without a key are omitted."""
    if not content or not isinstance(content, dict):
        return {}
    raw = content.get("questions")
    if not isinstance(raw, list):
        return {}
    key: dict[str, str] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        qid_raw = item.get("id")
        qid = (
            str(qid_raw).strip()[:_QUESTION_ID_MAX]
            if qid_raw is not None and str(qid_raw).strip()
            else f"q{index + 1}"
        )
        correct_raw = item.get("correct") or item.get("answer")
        if isinstance(correct_raw, str) and correct_raw.strip():
            key[qid] = _normalize_answer(correct_raw)
    return key


def _normalize_answer(value: str) -> str:
    return " ".join(value.strip().casefold().split())[:_CORRECT_MAX]


def score_quiz(
    content: dict[str, Any] | None,
    answers: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Score quiz answers on the backend. Returns None when no answer key exists."""
    key = parse_answer_key(content)
    if not key:
        return None
    given = answers if isinstance(answers, dict) else {}
    results: list[dict[str, Any]] = []
    correct_count = 0
    for question in parse_questions(content):
        expected = key.get(question["id"])
        if expected is None:
            results.append({"id": question["id"], "is_correct": None})
            continue
        raw = given.get(question["id"])
        actual = _normalize_answer(raw) if isinstance(raw, str) else ""
        is_correct = actual == expected
        if is_correct:
            correct_count += 1
        results.append({"id": question["id"], "is_correct": is_correct})
    total = len(key)
    return {
        "correct_count": correct_count,
        "total": total,
        "score": round(correct_count / total, 4) if total else 0.0,
        "results": results,
    }


def public_step_content(content: dict[str, Any] | None) -> dict[str, Any]:
    """Strip answer keys so employees cannot read the scoring key from the API."""
    if not isinstance(content, dict):
        return {}
    out = dict(content)
    raw = out.get("questions")
    if not isinstance(raw, list):
        return out
    cleaned: list[Any] = []
    for item in raw:
        if isinstance(item, dict):
            cleaned.append(
                {k: v for k, v in item.items() if k not in {"correct", "answer"}}
            )
        else:
            cleaned.append(item)
    out["questions"] = cleaned
    return out


def parse_url(content: dict[str, Any] | None) -> str | None:
    if not content or not isinstance(content, dict):
        return None
    for key in ("url", "link"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_URL_MAX]
    return None


def validate_step_content(step_type: str, content: dict[str, Any] | None) -> None:
    """Reject type-specific content that cannot be completed by an employee."""
    payload = content if isinstance(content, dict) else {}
    if step_type == StepType.QUIZ.value:
        if not parse_questions(payload):
            raise ValidationError(
                "quiz steps require at least one question in content.questions"
            )
    if step_type == StepType.TASK.value:
        url = payload.get("url") or payload.get("link")
        if url is not None and not isinstance(url, str):
            raise ValidationError("task content.url must be a string when set")


def validate_completion_payload(
    step_type: str,
    content: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> None:
    """Ensure the employee completion payload matches the step type."""
    body = payload if isinstance(payload, dict) else {}
    if step_type == StepType.ACK.value:
        if body.get("ack") is not True:
            raise ValidationError("Acknowledgement steps require payload.ack=true")
        return
    if step_type == StepType.QUIZ.value:
        questions = parse_questions(content)
        if not questions:
            raise ValidationError("quiz steps require questions before completion")
        answers = body.get("answers")
        if not isinstance(answers, dict):
            raise ValidationError("quiz completion requires payload.answers as an object")
        missing: list[str] = []
        for question in questions:
            raw = answers.get(question["id"])
            if not isinstance(raw, str) or not raw.strip():
                missing.append(question["id"])
            elif len(raw) > _ANSWER_MAX:
                raise ValidationError(
                    f"quiz answer for {question['id']!r} exceeds {_ANSWER_MAX} characters"
                )
        if missing:
            raise ValidationError(
                "quiz completion requires answers for all questions: "
                + ", ".join(missing)
            )
