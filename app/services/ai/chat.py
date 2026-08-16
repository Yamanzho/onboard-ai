"""Conversation-aware RAG chat. ACL is KnowledgeRetriever → ArticleService only.

HTTP surface is POST /api/v1/ai/chat. Telegram is a thin HTTP client (AI-9C)
and does not call this service directly. Conversation history is prompt
context only — not KB, not ACL, and not a citation source. Every turn
re-retrieves against live ArticleService permissions. No min_score.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.core.ai_constants import (
    DEFAULT_RETRIEVAL_TOP_K,
    MAX_CHAT_HISTORY_MESSAGES,
    MAX_CHAT_QUESTION_CHARS,
    MAX_CONVERSATION_MESSAGE_CHARS,
)
from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, ServiceUnavailableError, ValidationError
from app.core.request_id import request_id_log_value
from app.db.enums import ConversationStatus
from app.db.uow import UnitOfWork
from app.services.ai.context import Citation, KnowledgeContextBuilder
from app.services.ai.conversations import ConversationService
from app.services.ai.history import HistoryTurn, select_history_for_llm
from app.services.ai.llm import LLMProvider, get_llm_provider
from app.services.ai.metrics import incr, observe_hit_count, observe_latency_ms
from app.services.ai.prompts import RAG_SYSTEM_PROMPT, build_user_prompt
from app.services.ai.retriever import KnowledgeRetriever

logger = logging.getLogger("app.kb.chat")

NO_ANSWER_MESSAGE = "I could not find an answer in the company knowledge base."
_SOURCE_CITE_RE = re.compile(r"\[(S\d+)\]")


@dataclass(frozen=True, slots=True)
class ChatAnswer:
    """Structured RAG result. Citations come from supplied retrieval hits."""

    answer: str
    no_answer: bool
    citations: tuple[Citation, ...]
    model: str
    status: str
    hit_count: int
    conversation_id: UUID


class AIChatService:
    """Question → retrieve → context → LLM → persist turn → structured answer.

    Does not implement KB ACL. Does not query extra KB rows beyond
    KnowledgeRetriever hits. ConversationService owns persistence.
    """

    def __init__(
        self,
        *,
        retriever: KnowledgeRetriever | None = None,
        llm_provider: LLMProvider | None = None,
        context_builder: KnowledgeContextBuilder | None = None,
        conversation_service: ConversationService | None = None,
        uow_factory: Callable[[], UnitOfWork] | None = None,
    ) -> None:
        self._retriever = retriever or KnowledgeRetriever(uow_factory=uow_factory)
        self._llm_provider = llm_provider
        self._context_builder = context_builder or KnowledgeContextBuilder()
        self._conversations = conversation_service or ConversationService(
            uow_factory=uow_factory
        )

    def _llm(self) -> LLMProvider:
        return self._llm_provider or get_llm_provider()

    async def answer(
        self,
        question: str,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        conversation_id: UUID | None = None,
        claimed_company_id: UUID | None = None,
        top_k: int = DEFAULT_RETRIEVAL_TOP_K,
    ) -> ChatAnswer:
        started = time.perf_counter()
        result_status = "error"
        hit_count = 0
        citation_count = 0
        model_name = ""
        provider = get_settings().ai_llm_provider
        error_class = ""
        timeout = get_settings().ai_chat_timeout_seconds
        log_conversation_id = conversation_id

        async def _run() -> ChatAnswer:
            nonlocal result_status, hit_count, citation_count, model_name
            nonlocal log_conversation_id
            normalized = _validate_question(question)
            history = await self._load_history(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                conversation_id=conversation_id,
            )
            llm = self._llm()
            model_name = llm.model
            hits = await self._retriever.retrieve(
                normalized,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                claimed_company_id=claimed_company_id,
                top_k=top_k,
            )
            hit_count = len(hits)
            if not hits:
                result_status = "empty_retrieval"
                persisted = await self._persist_turn(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    conversation_id=conversation_id,
                    user_content=normalized,
                    assistant_content=NO_ANSWER_MESSAGE,
                    no_answer=True,
                )
                log_conversation_id = persisted.id
                return ChatAnswer(
                    answer=NO_ANSWER_MESSAGE,
                    no_answer=True,
                    citations=(),
                    model=model_name,
                    status=result_status,
                    hit_count=0,
                    conversation_id=persisted.id,
                )

            bundle = self._context_builder.build(hits)
            if not bundle.documents:
                result_status = "empty_retrieval"
                persisted = await self._persist_turn(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    conversation_id=conversation_id,
                    user_content=normalized,
                    assistant_content=NO_ANSWER_MESSAGE,
                    no_answer=True,
                )
                log_conversation_id = persisted.id
                return ChatAnswer(
                    answer=NO_ANSWER_MESSAGE,
                    no_answer=True,
                    citations=(),
                    model=model_name,
                    status=result_status,
                    hit_count=hit_count,
                    conversation_id=persisted.id,
                )

            generation = await llm.generate(
                system_prompt=RAG_SYSTEM_PROMPT,
                user_prompt=build_user_prompt(
                    normalized, bundle.documents, history=history
                ),
            )
            if generation.no_answer:
                result_status = "no_answer"
                persisted = await self._persist_turn(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    conversation_id=conversation_id,
                    user_content=normalized,
                    assistant_content=NO_ANSWER_MESSAGE,
                    no_answer=True,
                )
                log_conversation_id = persisted.id
                return ChatAnswer(
                    answer=NO_ANSWER_MESSAGE,
                    no_answer=True,
                    citations=(),
                    model=model_name,
                    status=result_status,
                    hit_count=hit_count,
                    conversation_id=persisted.id,
                )

            cited_ids = _SOURCE_CITE_RE.findall(generation.text)
            citations = bundle.citations_for(cited_ids) or bundle.citations
            citation_count = len(citations)
            result_status = "answered"
            persisted = await self._persist_turn(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                conversation_id=conversation_id,
                user_content=normalized,
                assistant_content=generation.text,
                citations=citations,
                no_answer=False,
            )
            log_conversation_id = persisted.id
            return ChatAnswer(
                answer=generation.text,
                no_answer=False,
                citations=citations,
                model=model_name,
                status=result_status,
                hit_count=hit_count,
                conversation_id=persisted.id,
            )

        try:
            return await asyncio.wait_for(_run(), timeout=timeout)
        except TimeoutError as exc:
            result_status = "timeout"
            error_class = "timeout"
            raise ServiceUnavailableError("AI chat timed out") from exc
        except ForbiddenError:
            result_status = "forbidden"
            raise
        except ServiceUnavailableError:
            result_status = "error"
            error_class = "unknown"
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            observe_latency_ms("chat", duration_ms)
            observe_hit_count(hit_count)
            incr(
                "ai_requests",
                provider=provider,
                operation="chat",
                result=(
                    result_status
                    if result_status
                    in {
                        "answered",
                        "empty_retrieval",
                        "no_answer",
                        "timeout",
                        "forbidden",
                    }
                    else "error"
                ),
                error_class=error_class,
            )
            logger.info(
                "kb_chat request_id=%s company_id=%s employee_id=%s actor_role=%s "
                "conversation_id=%s hit_count=%s citation_count=%s model=%s "
                "result=%s duration_ms=%.1f",
                request_id_log_value(),
                actor_company_id,
                actor_employee_id,
                actor_role,
                log_conversation_id or "",
                hit_count,
                citation_count,
                model_name,
                result_status,
                duration_ms,
            )

    async def _load_history(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        conversation_id: UUID | None,
    ) -> tuple[HistoryTurn, ...]:
        if conversation_id is None:
            return ()
        conversation = await self._conversations.get_conversation(
            actor_company_id,
            actor_employee_id,
            conversation_id,
        )
        if conversation.status == ConversationStatus.ARCHIVED.value:
            raise ValidationError("Cannot add messages to an archived conversation")
        recent = await self._conversations.list_recent_messages(
            actor_company_id,
            actor_employee_id,
            conversation.id,
            limit=MAX_CHAT_HISTORY_MESSAGES,
        )
        turns = tuple(
            HistoryTurn(role=message.role, content=message.content) for message in recent
        )
        return select_history_for_llm(turns)

    async def _persist_turn(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        conversation_id: UUID | None,
        user_content: str,
        assistant_content: str,
        citations: tuple[Citation, ...] = (),
        no_answer: bool = False,
    ):
        stored_assistant = assistant_content.strip()
        if len(stored_assistant) > MAX_CONVERSATION_MESSAGE_CHARS:
            stored_assistant = stored_assistant[:MAX_CONVERSATION_MESSAGE_CHARS]
        return await self._conversations.complete_turn(
            actor_company_id,
            actor_employee_id,
            user_content,
            stored_assistant,
            conversation_id=conversation_id,
            citations=_public_citations(citations),
            no_answer=no_answer,
        )


def _public_citations(citations: tuple[Citation, ...]) -> list[dict[str, str]] | None:
    if not citations:
        return None
    return [
        {
            "source_id": citation.source_id,
            "title": citation.title,
            "article_id": str(citation.article_id),
        }
        for citation in citations
    ]


def _validate_question(question: object) -> str:
    if not isinstance(question, str):
        raise ValidationError("question must be a string")
    stripped = question.strip()
    if not stripped:
        raise ValidationError("question must not be empty")
    if len(stripped) > MAX_CHAT_QUESTION_CHARS:
        raise ValidationError(
            f"question must be at most {MAX_CHAT_QUESTION_CHARS} characters"
        )
    return stripped
