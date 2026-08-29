"""ACL-first KB retriever with hybrid vector + FTS retrieval.

Authorization path (the only one):

    ArticleService.list_articles → allowed article ids → vector search
    inside that set, joined to live current_version_id + published status.

Chunk ``metadata`` / ``extra`` is never read for access control. Tenant comes
from the authenticated actor, never from query text, UUIDs in the query, or
spoofed JSON. Super Admin is ForbiddenError without impersonation.

No public ``/ai/search`` API. Chat is POST /api/v1/ai/chat via AIChatService.
Embeddings come from the configured EmbeddingProvider (fake in CI; OpenAI
text-embedding-3-small in production).

Hybrid retrieval (AI-hybrid-1)
-------------------------------
``retrieve()`` runs two independent searches and merges by ``chunk_id``:

1. Vector search — pgvector cosine distance (unchanged from AI-4).
2. Lexical search — PostgreSQL FTS with ``to_tsvector('simple', content)``
   and a sanitised ``to_tsquery`` built from alphanumeric query tokens.

Merged scoring:

* Vector-only: ``score = clamp(1 - cosine_distance, 0, 1)``
* Vector + lexical: ``score += LEXICAL_BOOST`` (applied exactly once)
* Lexical-only (not in vector top-N): ``score = LEXICAL_FLOOR_SCORE``

The ``lexical_score`` from ``ts_rank_cd`` is dimensionless and NOT added to
cosine similarity. It is used to (1) order FTS candidates before merging and
(2) pick the per-article reserved FTS slot so a strong lexical hit is not
dropped by higher-cosine neighbors from the same article.

Score is ``clamp(1 - cosine_distance, 0, 1)`` for ranking. Fake embeddings
are not calibrated semantic relevance; there is no production threshold.

Hyphenated Cyrillic compounds (``Стоп-фактор``) append a tsquery prefix
operator (``фактор:*``) on those Cyrillic hyphen parts only, so
``simple`` matching can hit inflected index forms such as ``факторы``
without changing the database text-search configuration.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.ai_constants import (
    DEFAULT_RETRIEVAL_TOP_K,
    KB_CHUNK_VECTOR_DIMENSION,
    LEXICAL_BOOST,
    LEXICAL_FLOOR_SCORE,
    LEXICAL_OVERFETCH,
    LEXICAL_RESERVED_PER_ARTICLE,
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

# Matches safe alphanumeric tokens in Cyrillic + Latin + digits.
# Strips punctuation, operators, and any character that could inject
# PostgreSQL tsquery syntax before the string reaches the DB.
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE | re.UNICODE)
_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE | re.UNICODE)
# ASCII hyphen plus common Unicode dashes used in KB headings.
_HYPHEN_COMPOUND_RE = re.compile(
    r"[a-zа-яё0-9]+(?:[\-\u2010\u2011\u2013\u2014][a-zа-яё0-9]+)+",
    re.IGNORECASE | re.UNICODE,
)


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
    """Return ranked current-published chunks the actor may already read.

    Uses hybrid retrieval: vector cosine search + PostgreSQL FTS merged by
    chunk_id. Both paths enforce the same ACL (allowed_article_ids) and the
    same tenant RLS context. See module docstring for scoring details.
    """

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
        embedding_query: str | None = None,
    ) -> list[RetrievalHit]:
        """ACL-first hybrid retrieval. ``claimed_company_id`` is untrusted if provided.

        ``min_score`` is an optional 0..1 cosine-similarity floor applied after
        merging. Default ``None`` applies no cutoff — fake embeddings cannot
        calibrate a production no-answer threshold.

        ``query`` is the original user question. Lexical/FTS always tokenises
        this string so conversation history cannot flip AND/OR or inject
        assistant terms into ``to_tsquery``.

        ``embedding_query`` is optional and used only for the vector embedding.
        Chat may pass a history-expanded string here; the LLM still receives
        the original question from AIChatService, never this value.
        """
        started = time.perf_counter()
        result_status = "error"
        hit_count = 0
        allowed_count = 0
        vector_candidates = 0
        lexical_candidates = 0
        resolved_top_k: int | None = None
        try:
            normalized = _validate_query(query)
            embed_text = (
                _validate_query(embedding_query)
                if embedding_query is not None
                else normalized
            )
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
            vector = await provider.embed(embed_text)
            if len(vector) != KB_CHUNK_VECTOR_DIMENSION:
                raise ValidationError(
                    "embedding dimension mismatch: expected "
                    f"{KB_CHUNK_VECTOR_DIMENSION}, got {len(vector)}"
                )

            overfetch = min(
                MAX_RETRIEVAL_CANDIDATES,
                max(resolved_top_k * MAX_CHUNKS_PER_ARTICLE_RESULT, resolved_top_k),
            )
            # FTS always uses the original question, never the embedding expansion.
            tsquery = _build_tsquery(normalized)

            async with self._uow_factory() as uow:
                await uow.enter_tenant(actor_company_id)
                vector_rows = await uow.knowledge_article_chunks.search_similar_current_published(
                    allowed_article_ids=allowed_ids,
                    query_embedding=vector,
                    limit=overfetch,
                )
                lexical_rows = []
                if tsquery:
                    lexical_rows = await uow.knowledge_article_chunks.search_lexical_current_published(
                        allowed_article_ids=allowed_ids,
                        tsquery_text=tsquery,
                        limit=LEXICAL_OVERFETCH,
                    )

            vector_candidates = len(vector_rows)
            lexical_candidates = len(lexical_rows)

            hits = _merge_and_score(
                vector_rows=vector_rows,
                lexical_rows=lexical_rows,
                top_k=resolved_top_k,
                min_score=min_score,
            )
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
                vector_candidates=vector_candidates,
                lexical_candidates=lexical_candidates,
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


def _hyphenated_cyrillic_tokens(query: str) -> frozenset[str]:
    """Cyrillic alphanumeric parts of hyphenated compounds in ``query``.

    Used to add a query-side ``:*`` prefix so ``simple`` FTS can match
    inflected forms (``фактор`` → ``факторы``) without stemming. Latin and
    numeric hyphen parts are left exact to avoid broad prefix matches
    (``cl:*``, ``p13:*``).
    """
    found: set[str] = set()
    for compound in _HYPHEN_COMPOUND_RE.findall(query):
        for part in _TOKEN_RE.findall(compound):
            token = part.lower()
            if len(token) > 1 and _CYRILLIC_RE.search(token):
                found.add(token)
    return frozenset(found)


def _tsquery_term(token: str, *, prefix_tokens: frozenset[str]) -> str:
    """Alphanumeric token, optionally with a server-added prefix operator."""
    if token in prefix_tokens:
        return f"{token}:*"
    return token


def _build_tsquery(query: str) -> str | None:
    """Convert a user query into a safe PostgreSQL ``to_tsquery('simple', ...)`` string.

    Only alphanumeric Cyrillic/Latin/digit tokens are extracted.  Single-char
    tokens (e.g. Cyrillic initials such as "Г." → "г") are discarded because
    they produce excessive false positives.

    Token joining:
    * ≤ 3 meaningful tokens  →  AND (``&``) for higher precision.
    * > 3 meaningful tokens  →  OR  (``|``) for higher recall.

    Hyphenated Cyrillic components receive a ``:*`` prefix operator so
    ``Стоп-фактор`` matches indexed ``стоп-факторы``. The colon is added
    by this function; it is never taken from user input.

    Returns ``None`` when no valid tokens remain (e.g. punctuation-only input)
    so callers can skip the lexical path entirely.

    **Security:** raw user input MUST NOT reach ``to_tsquery()`` directly.
    This function ensures only safe lowercase alphanumeric tokens are used.
    User-supplied tsquery operators (``&``, ``|``, ``!``, ``(``, ``)``, ``:``)
    are stripped by the token regex. The only ``:`` in the output is the
    prefix operator appended to selected hyphenated Cyrillic tokens.
    """
    tokens = [t.lower() for t in _TOKEN_RE.findall(query) if len(t) > 1]
    if not tokens:
        return None
    prefix_tokens = _hyphenated_cyrillic_tokens(query)
    terms = [_tsquery_term(token, prefix_tokens=prefix_tokens) for token in tokens]
    operator = " & " if len(tokens) <= 3 else " | "
    return operator.join(terms)


def _merge_and_score(
    *,
    vector_rows: list[tuple[KnowledgeArticleChunk, float, str]],
    lexical_rows: list[tuple[KnowledgeArticleChunk, float, str]],
    top_k: int,
    min_score: float | None,
) -> list[RetrievalHit]:
    """Merge vector and lexical candidates, assign hybrid scores, deduplicate.

    Scoring rules (see module docstring for rationale):
    * Vector-only:       ``final_score = clamp(1 - distance, 0, 1)``
    * Vector + lexical:  ``final_score = vector_score + LEXICAL_BOOST``
    * Lexical-only:      ``final_score = LEXICAL_FLOOR_SCORE``

    The ``ts_rank_cd`` value from lexical rows is not added to the cosine
    scale. It selects the per-article reserved FTS slot in
    ``_dedupe_and_score``.

    After scoring, the pool is sorted descending by ``final_score`` and the
    existing ``MAX_CHUNKS_PER_ARTICLE_RESULT`` cap and ``top_k`` limit are
    applied, with ``LEXICAL_RESERVED_PER_ARTICLE`` FTS slots reserved first.
    """
    # chunk_id → (chunk, final_score, title, lexical_rank or None)
    pool: dict[UUID, tuple[KnowledgeArticleChunk, float, str, float | None]] = {}

    for chunk, distance, title in vector_rows:
        score = _cosine_similarity_score(distance)
        pool[chunk.id] = (chunk, score, title, None)

    for chunk, lex_score, title in lexical_rows:
        # lex_score (ts_rank_cd) is intentionally not added to the cosine
        # scale — the two metrics are not comparable.
        if chunk.id in pool:
            existing_chunk, existing_score, existing_title, _ = pool[chunk.id]
            pool[chunk.id] = (
                existing_chunk,
                existing_score + LEXICAL_BOOST,
                existing_title,
                float(lex_score),
            )
        else:
            pool[chunk.id] = (chunk, LEXICAL_FLOOR_SCORE, title, float(lex_score))

    sorted_pool = sorted(pool.values(), key=lambda x: x[1], reverse=True)
    return _dedupe_and_score(sorted_pool, top_k=top_k, min_score=min_score)


def _log_retrieve(
    *,
    actor_company_id: UUID,
    actor_employee_id: UUID,
    actor_role: str,
    allowed_articles: int,
    vector_candidates: int,
    lexical_candidates: int,
    hit_count: int,
    top_k: object,
    result: str,
    duration_ms: float,
) -> None:
    """Operational retrieve log. Never include query, body, embeddings, or secrets."""
    logger.info(
        "kb_retrieve request_id=%s company_id=%s employee_id=%s actor_role=%s "
        "allowed_articles=%s vector_candidates=%s lexical_candidates=%s "
        "hit_count=%s top_k=%s result=%s duration_ms=%.1f",
        request_id_log_value(),
        actor_company_id,
        actor_employee_id,
        actor_role,
        allowed_articles,
        vector_candidates,
        lexical_candidates,
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


def _hit_from_pool(
    chunk: KnowledgeArticleChunk,
    score: float,
    title: str,
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk.id,
        article_id=chunk.article_id,
        version_id=chunk.version_id,
        chunk_index=chunk.chunk_index,
        article_title=title,
        content=chunk.content,
        score=score,
    )


def _reserved_lexical_chunks(
    sorted_pool: list[tuple[KnowledgeArticleChunk, float, str, float | None]],
    *,
    min_score: float | None,
) -> list[tuple[KnowledgeArticleChunk, float, str]]:
    """Strongest FTS hits per article, up to ``LEXICAL_RESERVED_PER_ARTICLE``.

    Ranking inside an article is ``ts_rank`` descending, then hybrid score.
    These slots are filled before score-order neighbors consume the
    per-article cap.
    """
    per_article: dict[
        UUID, list[tuple[float, float, KnowledgeArticleChunk, str]]
    ] = {}
    for chunk, score, title, lex_rank in sorted_pool:
        if lex_rank is None:
            continue
        if min_score is not None and score < min_score:
            continue
        per_article.setdefault(chunk.article_id, []).append(
            (lex_rank, score, chunk, title)
        )

    reserved: list[tuple[KnowledgeArticleChunk, float, str]] = []
    for rows in per_article.values():
        rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _lex_rank, score, chunk, title in rows[:LEXICAL_RESERVED_PER_ARTICLE]:
            reserved.append((chunk, score, title))
    # Higher hybrid score first among reserved so boosted FTS stays visible.
    reserved.sort(key=lambda item: item[1], reverse=True)
    return reserved


def _dedupe_and_score(
    sorted_pool: list[tuple[KnowledgeArticleChunk, float, str, float | None]],
    *,
    top_k: int,
    min_score: float | None,
) -> list[RetrievalHit]:
    """Apply reserved FTS slots, per-article chunk cap, and top_k.

    ``sorted_pool`` must already be sorted descending by final hybrid score.
    Queries with no lexical hits keep score-order ranking unchanged.
    """
    seen_ids: set[UUID] = set()
    seen_article: dict[UUID, int] = {}
    hits: list[RetrievalHit] = []

    for chunk, score, title in _reserved_lexical_chunks(
        sorted_pool, min_score=min_score
    ):
        if len(hits) >= top_k:
            break
        used = seen_article.get(chunk.article_id, 0)
        if used >= MAX_CHUNKS_PER_ARTICLE_RESULT:
            continue
        seen_ids.add(chunk.id)
        seen_article[chunk.article_id] = used + 1
        hits.append(_hit_from_pool(chunk, score, title))

    for chunk, score, title, _lex_rank in sorted_pool:
        if len(hits) >= top_k:
            break
        if chunk.id in seen_ids:
            continue
        if min_score is not None and score < min_score:
            continue
        used = seen_article.get(chunk.article_id, 0)
        if used >= MAX_CHUNKS_PER_ARTICLE_RESULT:
            continue
        seen_ids.add(chunk.id)
        seen_article[chunk.article_id] = used + 1
        hits.append(_hit_from_pool(chunk, score, title))
    return hits
