"""Minimal natural-language matching for QuestionTopic rows. Not KB categories."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.core.ai_constants import TOPIC_CLASSIFIER_MARKER
from app.db.models.question_topic import QuestionTopic
from app.services.ai.llm import LLMProvider, get_llm_provider
from app.services.assistant.intent_router import (
    _as_confidence,
    _parse_classifier_payload,
    normalize_query,
)

logger = logging.getLogger("app.assistant.topic")

_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"ноутбук", "ноутбуки", "laptop", "notebook", "компьютер", "компьютеры"}),
    frozenset({"отпуск", "отпуска", "vacation", "leave"}),
    frozenset({"зарплата", "зарплате", "salary", "payroll", "оклад"}),
    frozenset({"командировка", "командировки", "командировок", "travel"}),
    frozenset({"vpn", "впн"}),
    frozenset({"пропуск", "пропуска", "badge", "access"}),
)

_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class TopicMatch:
    topic_id: object
    name: str
    slug: str
    score: int
    used_llm: bool


class TopicMatcher:
    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._llm_provider = llm_provider

    def match_deterministic(
        self,
        message: str,
        topics: list[QuestionTopic],
    ) -> TopicMatch | None:
        normalized = normalize_query(message)
        if not normalized or not topics:
            return None
        tokens = set(_TOKEN_RE.findall(normalized))
        scored: list[TopicMatch] = []
        for topic in topics:
            if not topic.is_active:
                continue
            score = _score_topic(normalized, tokens, topic)
            if score <= 0:
                continue
            scored.append(
                TopicMatch(
                    topic_id=topic.id,
                    name=topic.name,
                    slug=topic.slug,
                    score=score,
                    used_llm=False,
                )
            )
        if not scored:
            return None
        scored.sort(key=lambda item: (-item.score, item.slug))
        best = scored[0]
        if len(scored) > 1 and scored[1].score == best.score:
            return None
        if best.score < 60:
            return None
        return best

    async def match(
        self,
        message: str,
        topics: list[QuestionTopic],
        *,
        topic_hint: str | None = None,
    ) -> TopicMatch | None:
        hinted = self._match_hint(topic_hint, topics)
        if hinted is not None:
            return hinted
        deterministic = self.match_deterministic(message, topics)
        if deterministic is not None:
            return deterministic
        if not topics:
            return None
        return await self._classify(message, topics)

    def _match_hint(
        self,
        topic_hint: str | None,
        topics: list[QuestionTopic],
    ) -> TopicMatch | None:
        if not topic_hint:
            return None
        return self.match_deterministic(topic_hint, topics)

    async def _classify(
        self,
        message: str,
        topics: list[QuestionTopic],
    ) -> TopicMatch | None:
        slugs = [topic.slug for topic in topics if topic.is_active]
        if not slugs:
            return None
        system = (
            f"{TOPIC_CLASSIFIER_MARKER}\n"
            "Choose at most one topic slug from the allowed list. "
            'JSON only: {"topic_slug":"<slug-or-null>","confidence":0.0}.'
        )
        user = f"Allowed slugs: {', '.join(slugs)}\nMessage: {message.strip()}"
        try:
            llm = self._llm_provider or get_llm_provider()
            result = await llm.generate(
                system_prompt=system,
                user_prompt=user,
            )
        except Exception:
            logger.warning("topic_classifier_failed", exc_info=True)
            return None
        parsed = _parse_classifier_payload(result.text)
        if parsed is None:
            return None
        slug = parsed.get("topic_slug")
        if not isinstance(slug, str) or not slug.strip():
            return None
        confidence = _as_confidence(parsed.get("confidence"))
        if confidence < 0.55:
            return None
        wanted = slug.strip().lower()
        for topic in topics:
            if topic.is_active and topic.slug.lower() == wanted:
                return TopicMatch(
                    topic_id=topic.id,
                    name=topic.name,
                    slug=topic.slug,
                    score=int(confidence * 100),
                    used_llm=True,
                )
        return None


def _score_topic(normalized: str, tokens: set[str], topic: QuestionTopic) -> int:
    name = normalize_query(topic.name)
    slug = normalize_query(topic.slug.replace("-", " "))
    if name and name in normalized:
        return 100
    if slug and slug in normalized:
        return 95
    name_tokens = set(_TOKEN_RE.findall(name))
    slug_tokens = set(_TOKEN_RE.findall(slug))
    if name_tokens and name_tokens <= tokens:
        return 80
    if slug_tokens and slug_tokens <= tokens:
        return 75
    aliases = _aliases_for(name_tokens | slug_tokens | {name, slug})
    if aliases & tokens:
        return 65
    return 0


def _aliases_for(topic_tokens: set[str]) -> set[str]:
    found: set[str] = set()
    haystack = {token for token in topic_tokens if token}
    for group in _ALIAS_GROUPS:
        if haystack & group:
            found.update(group)
    return found
