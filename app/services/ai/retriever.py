"""ACL-first KB retriever. Vector search is not an authorization source.

Authorization path (the only one):

    ArticleService.list_articles → allowed article ids → vector search
    inside that set, joined to live current_version_id + published status.

Chunk ``metadata`` / ``extra`` is never read for access control. Tenant comes
from the authenticated actor, never from query text, UUIDs in the query, or
spoofed JSON. Super Admin is ForbiddenError without impersonation.

No public `/ai/search` API. Chat is POST /api/v1/ai/chat via AIChatService.
Embeddings come from the configured EmbeddingProvider (fake in CI; OpenAI
text-embedding-3-small in production).

Score is ``clamp(1 - cosine_distance, 0, 1)`` for ranking. Fake embeddings
are not calibrated semantic relevance; there is no production threshold.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.ai_constants import (
    DEFAULT_RETRIEVAL_TOP_K,
    KB_CHUNK_VECTOR_DIMENSION,
    MAX_CHUNKS_PER_ARTICLE_RESULT,
    MAX_RETRIEVAL_CANDIDATES,
    MAX_RETRIEVAL_QUERY_CHARS,
    MAX_RETRIEVAL_TOP_K,
)
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.request_id import request_id_log_value
from app.db.enums import KnowledgeArticleStatus, PlatformRole
from app.db.models.knowledge_article_chunk import KnowledgeArticleChunk
from app.db.uow import UnitOfWork
from app.services.ai.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.tenancy import ensure_same_company

if TYPE_CHECKING:
    from app.services.knowledge.article_service import ArticleService

logger = logging.getLogger("app.kb.retrieve")

_ARTICLE_LIST_PAGE = 1000


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """Ranked chunk for a later citation renderer. Not an ACL grant."""

    chunk_id: UUID
    article_id: UUID
    version_id: UUID
    chunk_index: int
    article_title: str
    content: str
    score: float


class KnowledgeRetriever:
    """Return ranked current-published chunks the actor may already read."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        article_service: ArticleService | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        if article_service is None:
            from app.services.knowledge.article_service import ArticleService as ArticleServiceCls

            article_service = ArticleServiceCls(uow_factory=self._uow_factory)
        self._article_service = article_service
        self._embedding_provider = embedding_provider

    def _provider(self) -> EmbeddingProvider:
        return self._embedding_provider or get_embedding_provider()

    async def retrieve(
        self,
        query: str,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        top_k: int = DEFAULT_RETRIEVAL_TOP_K,
        claimed_company_id: UUID | None = None,
        min_score: float | None = None,
    ) -> list[RetrievalHit]:
        """ACL-first retrieval. ``claimed_company_id`` is untrusted if provided.

        ``min_score`` is an optional 0..1 cosine-similarity floor. Default
        ``None`` applies no cutoff — fake embeddings cannot calibrate a
        production no-answer threshold.
        """
        started = time.perf_counter()
        result_status = "error"
        hit_count = 0
        allowed_count = 0
        resolved_top_k: int | None = None
        try:
            normalized = _validate_query(query)
            resolved_top_k = _validate_top_k(top_k)
            _validate_min_score(min_score)

            if actor_role == PlatformRole.SUPER_ADMIN.value:
                result_status = "forbidden"
                raise ForbiddenError(
                    "Super Admin has no AI access without tenant impersonation"
                )

            if claimed_company_id is not None:
                ensure_same_company(
                    resource_company_id=claimed_company_id,
                    actor_company_id=actor_company_id,
                    not_found_message=f"Company {claimed_company_id} not found",
                )

            allowed_ids = await self._allowed_published_article_ids(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
            )
            allowed_count = len(allowed_ids)
            if not allowed_ids:
                result_status = "empty_acl"
                return []

            provider = self._provider()
            if provider.dimension != KB_CHUNK_VECTOR_DIMENSION:
                raise ValidationError(
                    "embedding dimension mismatch: provider="
                    f"{provider.dimension}, column={KB_CHUNK_VECTOR_DIMENSION}"
                )
            vector = await provider.embed(normalized)
            if len(vector) != KB_CHUNK_VECTOR_DIMENSION:
                raise ValidationError(
                    "embedding dimension mismatch: expected "
                    f"{KB_CHUNK_VECTOR_DIMENSION}, got {len(vector)}"
                )

            overfetch = min(
                MAX_RETRIEVAL_CANDIDATES,
                max(resolved_top_k * MAX_CHUNKS_PER_ARTICLE_RESULT, resolved_top_k),
            )
            async with self._uow_factory() as uow:
                await uow.enter_tenant(actor_company_id)
                rows = await uow.knowledge_article_chunks.search_similar_current_published(
                    allowed_article_ids=allowed_ids,
                    query_embedding=vector,
                    limit=overfetch,
                )

            hits = _dedupe_and_score(rows, top_k=resolved_top_k, min_score=min_score)
            hit_count = len(hits)
            result_status = "success"
            return hits
        except ForbiddenError:
            result_status = "forbidden"
            raise
        except NotFoundError:
            result_status = "not_found"
            raise
        except ValidationError:
            result_status = "invalid"
            raise
        except Exception:
            result_status = "error"
            raise
        finally:
            _log_retrieve(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                allowed_articles=allowed_count,
                hit_count=hit_count,
                top_k=resolved_top_k if resolved_top_k is not None else top_k,
                result=result_status,
                duration_ms=(time.perf_counter() - started) * 1000,
            )

    async def _allowed_published_article_ids(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
    ) -> list[UUID]:
        """Visible published article ids from ArticleService — not chunk metadata."""
        collected: list[UUID] = []
        offset = 0
        while True:
            page = await self._article_service.list_articles(
                actor_company_id,
                actor_company_id=actor_company_id,
                status=KnowledgeArticleStatus.PUBLISHED.value,
                offset=offset,
                limit=_ARTICLE_LIST_PAGE,
                actor_role=actor_role,
                actor_employee_id=actor_employee_id,
            )
            for article in page:
                if article.status != KnowledgeArticleStatus.PUBLISHED.value:
                    continue
                if article.current_version_id is None:
                    continue
                collected.append(article.id)
            if len(page) < _ARTICLE_LIST_PAGE:
                break
            offset += _ARTICLE_LIST_PAGE
        return collected


def _log_retrieve(
    *,
    actor_company_id: UUID,
    actor_employee_id: UUID,
    actor_role: str,
    allowed_articles: int,
    hit_count: int,
    top_k: object,
    result: str,
    duration_ms: float,
) -> None:
    """Operational retrieve log. Never include query, body, embeddings, or secrets."""
    logger.info(
        "kb_retrieve request_id=%s company_id=%s employee_id=%s actor_role=%s "
        "allowed_articles=%s hit_count=%s top_k=%s result=%s duration_ms=%.1f",
        request_id_log_value(),
        actor_company_id,
        actor_employee_id,
        actor_role,
        allowed_articles,
        hit_count,
        top_k,
        result,
        duration_ms,
    )


def _validate_query(query: object) -> str:
    if not isinstance(query, str):
        raise ValidationError("query must be a string")
    stripped = query.strip()
    if not stripped:
        raise ValidationError("query must not be empty")
    if len(stripped) > MAX_RETRIEVAL_QUERY_CHARS:
        raise ValidationError(
            f"query must be at most {MAX_RETRIEVAL_QUERY_CHARS} characters"
        )
    return stripped


def _validate_top_k(top_k: object) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ValidationError("top_k must be an integer")
    if top_k < 1 or top_k > MAX_RETRIEVAL_TOP_K:
        raise ValidationError(
            f"top_k must be between 1 and {MAX_RETRIEVAL_TOP_K}"
        )
    return top_k


def _validate_min_score(min_score: object) -> None:
    if min_score is None:
        return
    if isinstance(min_score, bool) or not isinstance(min_score, int | float):
        raise ValidationError("min_score must be a number")
    if min_score < 0.0 or min_score > 1.0:
        raise ValidationError("min_score must be between 0 and 1")


def _cosine_similarity_score(distance: float) -> float:
    """Map pgvector cosine distance to a clamped 0..1 similarity.

    Fake embeddings are L2-normalized, so cosine distance is 1 - dot(u, v)
    in [0, 2]. This score is a ranking convenience, not semantic relevance.
    """
    return max(0.0, min(1.0, 1.0 - distance))


def _dedupe_and_score(
    rows: list[tuple[KnowledgeArticleChunk, float, str]],
    *,
    top_k: int,
    min_score: float | None,
) -> list[RetrievalHit]:
    seen_article: dict[UUID, int] = {}
    hits: list[RetrievalHit] = []
    for chunk, distance, title in rows:
        score = _cosine_similarity_score(distance)
        if min_score is not None and score < min_score:
            continue
        used = seen_article.get(chunk.article_id, 0)
        if used >= MAX_CHUNKS_PER_ARTICLE_RESULT:
            continue
        seen_article[chunk.article_id] = used + 1
        hits.append(
            RetrievalHit(
                chunk_id=chunk.id,
                article_id=chunk.article_id,
                version_id=chunk.version_id,
                chunk_index=chunk.chunk_index,
                article_title=title,
                content=chunk.content,
                score=score,
            )
        )
        if len(hits) >= top_k:
            break
    return hits
