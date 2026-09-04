"""Deterministic-first intent routing. LLM classifier only when ambiguous."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.core.ai_constants import INTENT_CLASSIFIER_MARKER
from app.db.enums import AssistantIntent
from app.services.ai.llm import LLMProvider, get_llm_provider

logger = logging.getLogger("app.assistant.intent")

_VALID_INTENTS = {item.value for item in AssistantIntent}
_LLM_MIN_CONFIDENCE = 0.55

_PUNCT_RE = re.compile(r"[^\w\s?]+", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

_GREETING_EXACT = frozenset(
    {
        "привет",
        "приветствую",
        "здравствуй",
        "здравствуйте",
        "добро пожаловать",
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "hello",
        "hi",
        "hey",
        "salam",
        "салам",
        "салем",
        "сәлем",
        "хай",
    }
)
_THANKS_EXACT = frozenset(
    {
        "спасибо",
        "спасибо большое",
        "благодарю",
        "thanks",
        "thank you",
        "thx",
        "рахмет",
        "рахмет большое",
    }
)
_HELP_PHRASES = (
    "что ты умеешь",
    "чем ты можешь",
    "чем можешь помочь",
    "что ты можешь",
    "help",
    "помощь",
    "твои возможности",
)
_NEXT_TASK_PHRASES = (
    "что мне делать",
    "что мне нужно сделать",
    "что делать сегодня",
    "что дальше",
    "мои задачи",
    "какие у меня задания",
    "какие задания",
    "мои задания",
    "что делать",
)
_STATUS_PHRASES = (
    "какой у меня прогресс",
    "мой прогресс",
    "сколько осталось",
    "как дела с курсом",
    "статус задания",
    "статус курса",
)
_CONTINUE_PHRASES = (
    "продолжи курс",
    "продолжить курс",
    "продолжи обучение",
    "продолжить обучение",
    "открой курс",
    "открой обучение",
    "resume course",
    "continue learning",
)
_TRAINING_HELP_PHRASES = (
    "я не понял",
    "я не поняла",
    "не понял этот урок",
    "не поняла этот урок",
    "объясни это проще",
    "объясни проще",
    "что значит этот пункт",
    "что значит этот",
    "объясни урок",
    "не понял урок",
)
_RESPONSIBLE_PHRASES = (
    "кто отвечает",
    "кто отвечает за",
    "к кому обратиться",
    "кто занимается",
    "кто ответственный",
    "кто отвечает по",
    "who is responsible",
)
_KNOWLEDGE_PHRASES = (
    "как оформить",
    "какие правила",
    "что такое",
    "как получить",
    "как заказать",
    "политика",
    "инструкц",
    "командиров",
    "испытательн",
)


@dataclass(frozen=True, slots=True)
class RoutedIntent:
    intent: AssistantIntent
    confidence: float
    topic_hint: str | None
    used_llm: bool
    source: str


def normalize_query(text: str) -> str:
    lowered = text.strip().lower().replace("ё", "е")
    cleaned = _PUNCT_RE.sub(" ", lowered)
    return _SPACE_RE.sub(" ", cleaned).strip()


def looks_knowledge_like(text: str) -> bool:
    normalized = normalize_query(text)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _KNOWLEDGE_PHRASES):
        return True
    if "?" in text and len(normalized) >= 8:
        return True
    if normalized.startswith(("как ", "what ", "how ")):
        return True
    return False


class IntentRouter:
    """Rules first. Structured LLM classification only if still unknown."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._llm_provider = llm_provider

    def route_deterministic(self, message: str) -> RoutedIntent | None:
        normalized = normalize_query(message)
        if not normalized:
            return RoutedIntent(
                AssistantIntent.UNKNOWN, 0.0, None, False, "empty"
            )
        if any(phrase in normalized for phrase in _RESPONSIBLE_PHRASES):
            return RoutedIntent(
                AssistantIntent.RESPONSIBLE_TOPIC, 1.0, None, False, "rule"
            )
        if any(phrase in normalized for phrase in _CONTINUE_PHRASES):
            return RoutedIntent(
                AssistantIntent.CONTINUE_LEARNING, 1.0, None, False, "rule"
            )
        if any(phrase in normalized for phrase in _TRAINING_HELP_PHRASES):
            return RoutedIntent(
                AssistantIntent.TRAINING_HELP, 1.0, None, False, "rule"
            )
        if any(phrase in normalized for phrase in _NEXT_TASK_PHRASES):
            return RoutedIntent(
                AssistantIntent.NEXT_TASK, 1.0, None, False, "rule"
            )
        if any(phrase in normalized for phrase in _STATUS_PHRASES):
            return RoutedIntent(
                AssistantIntent.ASSIGNMENT_STATUS, 1.0, None, False, "rule"
            )
        if any(phrase in normalized for phrase in _HELP_PHRASES):
            return RoutedIntent(
                AssistantIntent.HELP, 1.0, None, False, "rule"
            )
        if _is_exact_or_short(normalized, _THANKS_EXACT):
            return RoutedIntent(AssistantIntent.THANKS, 1.0, None, False, "rule")
        if _is_exact_or_short(normalized, _GREETING_EXACT):
            return RoutedIntent(
                AssistantIntent.GREETING, 1.0, None, False, "rule"
            )
        if looks_knowledge_like(message):
            return RoutedIntent(
                AssistantIntent.COMPANY_KNOWLEDGE, 0.85, None, False, "rule"
            )
        return None

    async def route(self, message: str) -> RoutedIntent:
        deterministic = self.route_deterministic(message)
        if deterministic is not None:
            return deterministic
        classified = await self._classify(message)
        if classified is not None:
            return classified
        if looks_knowledge_like(message):
            return RoutedIntent(
                AssistantIntent.COMPANY_KNOWLEDGE, 0.4, None, True, "fallback"
            )
        return RoutedIntent(
            AssistantIntent.UNKNOWN, 0.2, None, True, "fallback"
        )

    async def _classify(self, message: str) -> RoutedIntent | None:
        system = (
            f"{INTENT_CLASSIFIER_MARKER}\n"
            "Classify the employee message into exactly one intent. "
            "Reply with JSON only: "
            '{"intent":"<intent>","confidence":0.0,"topic_hint":""}. '
            f"intent must be one of: {', '.join(sorted(_VALID_INTENTS))}."
        )
        try:
            llm = self._llm_provider or get_llm_provider()
            result = await llm.generate(
                system_prompt=system,
                user_prompt=message.strip(),
            )
        except Exception:
            logger.warning("intent_classifier_failed", exc_info=True)
            return None
        parsed = _parse_classifier_payload(result.text)
        if parsed is None:
            return None
        intent_raw = parsed.get("intent")
        if intent_raw not in _VALID_INTENTS:
            return None
        confidence = _as_confidence(parsed.get("confidence"))
        if confidence < _LLM_MIN_CONFIDENCE:
            return None
        hint = parsed.get("topic_hint")
        topic_hint = hint.strip() if isinstance(hint, str) and hint.strip() else None
        return RoutedIntent(
            AssistantIntent(intent_raw),
            confidence,
            topic_hint,
            True,
            "llm",
        )


def _is_exact_or_short(normalized: str, phrases: frozenset[str]) -> bool:
    if normalized in phrases:
        return True
    for phrase in phrases:
        if normalized == phrase or normalized.startswith(f"{phrase} "):
            remainder = normalized[len(phrase) :].strip()
            if len(remainder.split()) <= 2 and not looks_knowledge_like(remainder):
                return True
    return False


def _parse_classifier_payload(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _as_confidence(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number
