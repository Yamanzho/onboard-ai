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
    SHORT_QUERY_EXPANSION_MAX_CHARS,
    SHORT_QUERY_EXPANSION_WORDS,
)
from app.core.config import get_settings
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
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
from app.services.idempotency import (
    IdempotencyClaim,
    IdempotencyService,
    hash_ai_request,
)
from app.services.telegram_format import format_ai_reply
from app.services.telegram_outbound import TelegramOutboundService

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
        idempotency_service: IdempotencyService | None = None,
        telegram_outbound_service: TelegramOutboundService | None = None,
        uow_factory: Callable[[], UnitOfWork] | None = None,
    ) -> None:
        self._retriever = retriever or KnowledgeRetriever(uow_factory=uow_factory)
        self._llm_provider = llm_provider
        self._context_builder = context_builder or KnowledgeContextBuilder()
        self._conversations = conversation_service or ConversationService(
            uow_factory=uow_factory
        )
        self._idempotency = idempotency_service or IdempotencyService()
        self._telegram_outbound = (
            telegram_outbound_service or TelegramOutboundService()
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
        idempotency_key: str | None = None,
        on_idempotency_acquired: Callable[[], None] | None = None,
        telegram_delivery: bool = False,
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
        idempotency_claim: IdempotencyClaim | None = None
        recovered_conversation_id: UUID | None = None

        async def _run() -> ChatAnswer:
            nonlocal result_status, hit_count, citation_count, model_name
            nonlocal log_conversation_id, idempotency_claim
            nonlocal recovered_conversation_id
            normalized = _validate_question(question)
            if telegram_delivery and idempotency_key is None:
                raise ValidationError(
                    "Telegram delivery requires an idempotency key"
                )
            if idempotency_key is not None:
                idempotency_claim = await self._idempotency.claim_ai_turn(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    idempotency_key=idempotency_key,
                    request_hash=hash_ai_request(
                        message=normalized,
                        # A Redis conversation pointer is routing state, not part
                        # of one Telegram update's stable semantic identity.
                        conversation_id=(
                            None if telegram_delivery else conversation_id
                        ),
                    ),
                )
                if idempotency_claim.state == "completed":
                    result_status = "idempotent_replay"
                    cached = _chat_answer_from_cached(idempotency_claim.response)
                    if telegram_delivery:
                        assert idempotency_key is not None
                        await self._telegram_outbound.enqueue_for_employee(
                            company_id=actor_company_id,
                            employee_id=actor_employee_id,
                            source_type="ai_chat",
                            source_key=idempotency_key,
                            body=format_ai_reply(
                                {
                                    "answer": cached.answer,
                                    "no_answer": cached.no_answer,
                                    "citations": _public_citations(
                                        cached.citations
                                    )
                                    or [],
                                }
                            ),
                        )
                    model_name = cached.model
                    citation_count = len(cached.citations)
                    log_conversation_id = cached.conversation_id
                    return cached
                if not idempotency_claim.acquired:
                    result_status = "idempotency_in_progress"
                    raise ConflictError("An identical AI request is already processing")
                if on_idempotency_acquired is not None:
                    on_idempotency_acquired()
            history, active_conversation_id = await self._load_history(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                conversation_id=conversation_id,
                recover_invalid_conversation=telegram_delivery,
            )
            if conversation_id is not None and active_conversation_id is None:
                recovered_conversation_id = conversation_id
            llm = self._llm()
            model_name = llm.model
            # Expand conversational follow-ups for the embedding query only.
            # Standalone topic nouns are not expanded. Lexical/FTS and the
            # LLM always use `normalized` (original question).
            embedding_query = _expand_query_with_history(normalized, history)
            hits = await self._retriever.retrieve(
                normalized,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                claimed_company_id=claimed_company_id,
                top_k=top_k,
                embedding_query=embedding_query,
            )
            hit_count = len(hits)
            if not hits:
                result_status = "empty_retrieval"
                persisted = await self._persist_turn(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    conversation_id=active_conversation_id,
                    user_content=normalized,
                    assistant_content=NO_ANSWER_MESSAGE,
                    no_answer=True,
                    idempotency_claim=idempotency_claim,
                    model=model_name,
                    result_status=result_status,
                    hit_count=0,
                    idempotency_key=idempotency_key,
                    telegram_delivery=telegram_delivery,
                )
                log_conversation_id = persisted.id
                self._log_stale_recovery(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    stale_conversation_id=recovered_conversation_id,
                    fresh_conversation_id=persisted.id,
                )
                return ChatAnswer(
                    answer=NO_ANSWER_MESSAGE,
                    no_answer=True,
                    citations=(),
                    model=model_name,
                    status=result_status,
                    hit_count=0,
                    conversation_id=persisted.id,
                )

            bundle = self._context_builder.build(hits, query=normalized)
            if not bundle.documents:
                result_status = "empty_retrieval"
                persisted = await self._persist_turn(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    conversation_id=active_conversation_id,
                    user_content=normalized,
                    assistant_content=NO_ANSWER_MESSAGE,
                    no_answer=True,
                    idempotency_claim=idempotency_claim,
                    model=model_name,
                    result_status=result_status,
                    hit_count=hit_count,
                    idempotency_key=idempotency_key,
                    telegram_delivery=telegram_delivery,
                )
                log_conversation_id = persisted.id
                self._log_stale_recovery(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    stale_conversation_id=recovered_conversation_id,
                    fresh_conversation_id=persisted.id,
                )
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
                    normalized,
                    bundle.documents,
                    history=history,
                    grounded_entity_note=bundle.grounded_entity_note,
                ),
            )
            if generation.no_answer:
                result_status = "no_answer"
                persisted = await self._persist_turn(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    conversation_id=active_conversation_id,
                    user_content=normalized,
                    assistant_content=NO_ANSWER_MESSAGE,
                    no_answer=True,
                    idempotency_claim=idempotency_claim,
                    model=model_name,
                    result_status=result_status,
                    hit_count=hit_count,
                    idempotency_key=idempotency_key,
                    telegram_delivery=telegram_delivery,
                )
                log_conversation_id = persisted.id
                self._log_stale_recovery(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    stale_conversation_id=recovered_conversation_id,
                    fresh_conversation_id=persisted.id,
                )
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
                conversation_id=active_conversation_id,
                user_content=normalized,
                assistant_content=generation.text,
                citations=citations,
                no_answer=False,
                idempotency_claim=idempotency_claim,
                model=model_name,
                result_status=result_status,
                hit_count=hit_count,
                idempotency_key=idempotency_key,
                telegram_delivery=telegram_delivery,
            )
            log_conversation_id = persisted.id
            self._log_stale_recovery(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                stale_conversation_id=recovered_conversation_id,
                fresh_conversation_id=persisted.id,
            )
            return ChatAnswer(
                answer=generation.text,
                no_answer=False,
                citations=citations,
                model=model_name,
                status=result_status,
                hit_count=hit_count,
                conversation_id=persisted.id,
            )

        async def _fail_owned_claim() -> None:
            if (
                idempotency_claim is None
                or not idempotency_claim.acquired
                or idempotency_claim.owner_token is None
            ):
                return
            try:
                await self._idempotency.fail_ai_turn(
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                    receipt_id=idempotency_claim.receipt_id,
                    owner_token=idempotency_claim.owner_token,
                )
            except Exception:
                logger.exception(
                    "kb_chat request_id=%s company_id=%s employee_id=%s "
                    "result=idempotency_fail_transition_error",
                    request_id_log_value(),
                    actor_company_id,
                    actor_employee_id,
                )

        try:
            return await asyncio.wait_for(_run(), timeout=timeout)
        except TimeoutError as exc:
            result_status = "timeout"
            error_class = "timeout"
            await _fail_owned_claim()
            raise ServiceUnavailableError("AI chat timed out") from exc
        except ForbiddenError:
            result_status = "forbidden"
            await _fail_owned_claim()
            raise
        except ServiceUnavailableError:
            result_status = "error"
            error_class = "unknown"
            await _fail_owned_claim()
            raise
        except Exception:
            await _fail_owned_claim()
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
                        "idempotent_replay",
                        "idempotency_in_progress",
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
        recover_invalid_conversation: bool = False,
    ) -> tuple[tuple[HistoryTurn, ...], UUID | None]:
        if conversation_id is None:
            return (), None
        try:
            conversation = await self._conversations.get_conversation(
                actor_company_id,
                actor_employee_id,
                conversation_id,
            )
        except NotFoundError:
            if not recover_invalid_conversation:
                raise
            # Trusted Telegram delivery is authenticated by the HTTP adapter.
            # Its Redis pointer is recoverable routing state. Generic API calls
            # retain the existing not-found/ownership behavior.
            return (), None
        if conversation.status == ConversationStatus.ARCHIVED.value:
            if recover_invalid_conversation:
                return (), None
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
        return select_history_for_llm(turns), conversation.id

    @staticmethod
    def _log_stale_recovery(
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        stale_conversation_id: UUID | None,
        fresh_conversation_id: UUID,
    ) -> None:
        if stale_conversation_id is None:
            return
        logger.info(
            "kb_chat_stale_recovery request_id=%s company_id=%s employee_id=%s "
            "old_conversation_id=%s new_conversation_id=%s outcome=recovered",
            request_id_log_value(),
            actor_company_id,
            actor_employee_id,
            stale_conversation_id,
            fresh_conversation_id,
        )

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
        idempotency_claim: IdempotencyClaim | None = None,
        model: str,
        result_status: str,
        hit_count: int,
        idempotency_key: str | None,
        telegram_delivery: bool,
    ):
        stored_assistant = assistant_content.strip()
        if len(stored_assistant) > MAX_CONVERSATION_MESSAGE_CHARS:
            stored_assistant = stored_assistant[:MAX_CONVERSATION_MESSAGE_CHARS]
        public_citations = _public_citations(citations)
        owned_claim = (
            idempotency_claim
            if idempotency_claim is not None and idempotency_claim.acquired
            else None
        )
        telegram_body = (
            format_ai_reply(
                {
                    "answer": assistant_content,
                    "no_answer": no_answer,
                    "citations": public_citations or [],
                }
            )
            if telegram_delivery
            else None
        )
        return await self._conversations.complete_turn(
            actor_company_id,
            actor_employee_id,
            user_content,
            stored_assistant,
            conversation_id=conversation_id,
            citations=public_citations,
            no_answer=no_answer,
            idempotency_receipt_id=(
                owned_claim.receipt_id if owned_claim is not None else None
            ),
            idempotency_owner_token=(
                owned_claim.owner_token if owned_claim is not None else None
            ),
            idempotency_response=(
                {
                    "answer": assistant_content,
                    "no_answer": no_answer,
                    "citations": _idempotency_citations(citations),
                    "model": model,
                    "status": result_status,
                    "hit_count": hit_count,
                }
                if owned_claim is not None
                else None
            ),
            telegram_outbound_source_key=(
                idempotency_key if telegram_delivery else None
            ),
            telegram_outbound_body=telegram_body,
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


def _idempotency_citations(
    citations: tuple[Citation, ...],
) -> list[dict[str, str | int]]:
    return [
        {
            "source_id": citation.source_id,
            "title": citation.title,
            "article_id": str(citation.article_id),
            "version_id": str(citation.version_id),
            "chunk_index": citation.chunk_index,
        }
        for citation in citations
    ]


def _chat_answer_from_cached(payload: dict | None) -> ChatAnswer:
    """Rehydrate a completed response without retrieval or provider calls."""
    if not isinstance(payload, dict):
        raise ServiceUnavailableError("Stored AI response is unavailable")
    try:
        raw_citations = payload.get("citations") or []
        citations = tuple(
            Citation(
                source_id=str(item["source_id"]),
                title=str(item["title"]),
                article_id=UUID(str(item["article_id"])),
                version_id=UUID(str(item["version_id"])),
                chunk_index=int(item["chunk_index"]),
            )
            for item in raw_citations
            if isinstance(item, dict)
        )
        return ChatAnswer(
            answer=str(payload["answer"]),
            no_answer=bool(payload["no_answer"]),
            citations=citations,
            model=str(payload.get("model") or ""),
            status="idempotent_replay",
            hit_count=int(payload.get("hit_count") or 0),
            conversation_id=UUID(str(payload["conversation_id"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceUnavailableError("Stored AI response is unavailable") from exc


# Discourse / pronoun / question-word heads that mark a short follow-up.
# Standalone topic nouns (CRM, AI-ассистент, Евгений) are not in this set.
_FOLLOW_UP_HEADS = frozenset(
    {
        "а",
        "кто",
        "что",
        "где",
        "когда",
        "почему",
        "зачем",
        "как",
        "какой",
        "какая",
        "какие",
        "который",
        "которая",
        "он",
        "она",
        "они",
        "это",
        "этот",
        "эта",
        "дальше",
        "потом",
        "ещё",
        "еще",
        "подробнее",
        "who",
        "what",
        "where",
        "why",
        "how",
        "which",
        "more",
        "continue",
    }
)
_FOLLOW_UP_STRIP = "?!.,:;…"


def _is_conversational_follow_up(query: str) -> bool:
    """True when ``query`` is a short anaphoric follow-up, not a topic noun."""
    words = [part.strip(_FOLLOW_UP_STRIP) for part in query.split()]
    words = [part for part in words if part]
    if not words:
        return False
    head = words[0].casefold()
    return head in _FOLLOW_UP_HEADS


def _expand_query_with_history(
    query: str,
    history: tuple[HistoryTurn, ...],
) -> str:
    """Return a retrieval-only expansion of ``query`` using conversation history.

    Purpose: short *conversational follow-ups* such as "а дальше?" or
    "кто отвечает?" can be expanded with the last assistant reply so the
    *vector* embedding has richer context. Standalone topic queries
    ("CRM", "AI-ассистент", "Евгений") must keep their own embedding so a
    previous answer cannot dominate retrieval.

    Lexical/FTS must keep the original ``query`` so assistant text cannot
    change tsquery AND/OR or drown exact-name matches.

    The expanded string is used ONLY as ``embedding_query``. The LLM always
    receives the original ``query`` as the user question.

    Trigger conditions (all must hold):
    * ``query`` contains at most ``SHORT_QUERY_EXPANSION_WORDS`` whitespace-
      separated words (default 2).
    * ``query`` is a conversational follow-up (pronoun / question-word /
      continuation), not a standalone topic noun.
    * ``history`` contains at least one assistant turn whose content is not
      the exact ``NO_ANSWER_MESSAGE``.

    The expansion concatenates ``query`` and the latest assistant content,
    trimmed to ``SHORT_QUERY_EXPANSION_MAX_CHARS``. Otherwise the original
    query is returned unchanged.

    Security: the expanded string is sent to the embedding provider only.
    It is never used as an LLM instruction or as the user-visible question.
    """
    if len(query.split()) > SHORT_QUERY_EXPANSION_WORDS:
        return query
    if not _is_conversational_follow_up(query):
        return query
    if not history:
        return query
    last_assistant = next(
        (t.content for t in reversed(history) if t.role == "assistant"),
        None,
    )
    if not last_assistant:
        return query
    if last_assistant.strip() == NO_ANSWER_MESSAGE:
        return query
    combined = f"{query} {last_assistant}"
    return combined[:SHORT_QUERY_EXPANSION_MAX_CHARS]


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
