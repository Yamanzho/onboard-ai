"""Parse onboarding step.content JSONB and validate completion payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.exceptions import ValidationError
from app.db.enums import StepType
from app.services.assessment import (
    is_structured_quiz,
    parse_structured_quiz,
    public_quiz_content,
    validate_quiz_answers,
)

_QUESTION_ID_MAX = 64
_QUESTION_TEXT_MAX = 500
_MAX_QUESTIONS = 20
_ANSWER_MAX = 2000
_URL_MAX = 2048
_CORRECT_MAX = 500
_MAX_CONTENT_BLOCKS = 100
_BLOCK_TEXT_MAX = 20000
_BLOCK_ID_MAX = 64
_ALLOWED_BLOCK_TYPES = frozenset({"text"})


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
    return public_quiz_content(content)


def parse_url(content: dict[str, Any] | None) -> str | None:
    if not content or not isinstance(content, dict):
        return None
    for key in ("url", "link"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_URL_MAX]
    return None


@dataclass(frozen=True, slots=True)
class ContentBlock:
    """Normalized ordered text block for a Step (inline training)."""

    id: str
    type: str
    text: str


def normalize_step_content(content: dict[str, Any] | None) -> list[ContentBlock]:
    """Read-only compatibility: new ``blocks`` schema or legacy body/text.

    Does not mutate the stored JSON. Unknown/invalid block items are skipped
    on read so old programs keep rendering.
    """
    if not content or not isinstance(content, dict):
        return []

    raw_blocks = content.get("blocks")
    if isinstance(raw_blocks, list) and raw_blocks:
        blocks: list[ContentBlock] = []
        for index, item in enumerate(raw_blocks):
            if len(blocks) >= _MAX_CONTENT_BLOCKS:
                break
            parsed = _parse_block_item(item, index)
            if parsed is not None:
                blocks.append(parsed)
        if blocks:
            return blocks

    for key in ("body", "text"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return [
                ContentBlock(id="legacy-body", type="text", text=value.strip()),
            ]
    return []


def content_blocks_as_dicts(content: dict[str, Any] | None) -> list[dict[str, str]]:
    return [
        {"id": block.id, "type": block.type, "text": block.text}
        for block in normalize_step_content(content)
    ]


def payload_block_index(payload: dict[str, Any] | None) -> int | None:
    """Current content-block cursor from Progress.payload, if present."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("block_index")
    if isinstance(raw, int) and raw >= 0:
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _parse_block_item(item: Any, index: int) -> ContentBlock | None:
    if not isinstance(item, dict):
        return None
    block_type = item.get("type") or "text"
    if not isinstance(block_type, str) or block_type not in _ALLOWED_BLOCK_TYPES:
        return None
    text_raw = item.get("text")
    if text_raw is None:
        text_raw = item.get("body")
    if not isinstance(text_raw, str):
        return None
    id_raw = item.get("id")
    block_id = (
        str(id_raw).strip()[:_BLOCK_ID_MAX]
        if id_raw is not None and str(id_raw).strip()
        else f"block-{index + 1}"
    )
    return ContentBlock(id=block_id, type="text", text=text_raw[:_BLOCK_TEXT_MAX])


def _validate_content_blocks(payload: dict[str, Any]) -> None:
    if "blocks" not in payload:
        return
    raw = payload["blocks"]
    if not isinstance(raw, list):
        raise ValidationError("content.blocks must be a list")
    if len(raw) > _MAX_CONTENT_BLOCKS:
        raise ValidationError(
            f"content.blocks cannot contain more than {_MAX_CONTENT_BLOCKS} items"
        )
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"content.blocks[{index}] must be an object")
        block_type = item.get("type", "text")
        if not isinstance(block_type, str) or block_type not in _ALLOWED_BLOCK_TYPES:
            raise ValidationError(
                f"content.blocks[{index}].type must be one of {sorted(_ALLOWED_BLOCK_TYPES)}"
            )
        text_raw = item.get("text")
        if text_raw is None:
            text_raw = item.get("body")
        if not isinstance(text_raw, str):
            raise ValidationError(f"content.blocks[{index}].text must be a string")
        if len(text_raw) > _BLOCK_TEXT_MAX:
            raise ValidationError(
                f"content.blocks[{index}].text exceeds {_BLOCK_TEXT_MAX} characters"
            )
        id_raw = item.get("id")
        if id_raw is not None and not isinstance(id_raw, str):
            raise ValidationError(f"content.blocks[{index}].id must be a string when set")


def validate_step_content(step_type: str, content: dict[str, Any] | None) -> None:
    """Reject type-specific content that cannot be completed by an employee."""
    payload = content if isinstance(content, dict) else {}
    _validate_content_blocks(payload)
    if step_type == StepType.QUIZ.value:
        if is_structured_quiz(payload):
            parse_structured_quiz(payload)
        elif not parse_questions(payload):
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
        if is_structured_quiz(content):
            quiz = parse_structured_quiz(content)
            validate_quiz_answers(quiz, body.get("answers"))
            return
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
