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

Standalone entity queries and explicit definition questions additionally
embed a script-folded identifier (same Latin↔Cyrillic token fold as FTS),
union those vector hits with the normal query embedding by ``chunk_id``,
and reserve the best definition-like match before the per-article cap.
Structured ``canonical_name`` / ``aliases`` records outrank heading/copula
matches. ENTITY identifiers are never names. Only the lookup term is
folded — not an arbitrary natural-language sentence. Process questions
and follow-ups skip this path. Hybrid scoring is unchanged. Definition
lookups run FTS on the lookup term (plus script variants), not question
words such as ``что`` / ``такое``.
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
    DEFINITION_RESERVED,
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
_DASH_RE = re.compile(r"[\u2010\u2011\u2013\u2014]")
_QUERY_PUNCT = "?!.,:;…"
# Conversational / process heads — not standalone entity lookups.
# Kept local to avoid importing chat.py (circular).
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
        "when",
        "whose",
        "whom",
    }
)
_FUNCTION_WORDS = frozenset(
    {
        "в",
        "на",
        "с",
        "со",
        "для",
        "по",
        "от",
        "до",
        "из",
        "к",
        "ко",
        "о",
        "об",
        "и",
        "или",
        "но",
        "не",
        "ни",
        "после",
        "при",
        "без",
        "над",
        "под",
        "между",
        "нужны",
        "нужно",
        "происходит",
        "делать",
        "документы",
        "the",
        "a",
        "an",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "by",
        "with",
        "after",
        "before",
        "about",
        "from",
        "into",
        "needed",
        "documents",
        "happens",
    }
)
_DEFINITION_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"что\s+такое|"
    r"что\s+это(?:\s+такое)?|"
    r"что\s+означает|"
    r"что\s+значит|"
    r"кто\s+так(?:ой|ая|ое|ие)|"
    r"дай(?:те)?\s+определение(?:\s+(?:для|слова))?|"
    r"определение(?:\s+(?:для|слова))?|"
    r"what\s+is(?:\s+an?)?|"
    r"what's|"
    r"define|"
    r"definition\s+of"
    r")\s+",
    re.IGNORECASE | re.UNICODE,
)
_COPULA_AFTER_RE = re.compile(
    r"(?:\s*(?:—|–|−)\s*(?:это\s+)?|"
    r"\s+-\s+(?:это\s+)?|"
    r"-\s+это\s+|"
    r"\s+это\s+|"
    r"\s+представляет\s+собой\s+|"
    r"\s+является\s+|"
    r"\s+определяется\s+как\s+|"
    r"\s+означает\s+|"
    r"\s+значит\s+|"
    r"\s+is\s+(?:a|an|the)\s+|"
    r"\s+means\s+)",
    re.IGNORECASE | re.UNICODE,
)
_COPULA_BEFORE_RE = re.compile(
    r"(?:это|called|named)\s+$",
    re.IGNORECASE | re.UNICODE,
)
_USAGE_RE = re.compile(
    r"использует(?:ся)?|указан[аоы]?|появля(?:ет(?:ся)?|ют(?:ся)?)|"
    r"примен(?:яет(?:ся)?|ени)|передач|"
    r"\bused\b|\bappears\b|\bmentioned\b",
    re.IGNORECASE | re.UNICODE,
)
_CANONICAL_RE = re.compile(
    r"каноническ|определени|основн(?:ой|ая|ое|ые)|canonical|definition",
    re.IGNORECASE | re.UNICODE,
)
_MAX_ENTITY_QUERY_WORDS = 3
_MIN_DEFINITION_SCORE = 3.0
# Production IDs look like SAELOG-ORG-0001 / SAELOG-SYS-0001. Never names.
_ENTITY_ID_RE = re.compile(r"^[A-Za-z0-9]+-[A-Z]+-\d+$")
_ENTITY_HEADER_RE = re.compile(
    r"^(?:#{1,6}\s+)?ENTITY\s+(\S.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ENTITY_FIELD_RE = re.compile(
    r"^[`\s\-\*]*`?(entity_type|canonical_name|aliases|description)"
    r"\s*:?\s*`?\s*:?\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ENTITY_TYPE_RANK = {
    "ORGANIZATION": 6,
    "SYSTEM": 5,
    "PRODUCT": 4,
    "SERVICE": 3,
    "DEPARTMENT": 2,
    "DOCUMENT": 1,
    "PERSON": 0,
}
# Cyrillic → Latin fold for identifier matching (visual + phonetic).
_CYR_TO_LAT: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}
_LAT_TO_CYR: dict[str, str] = {
    "a": "а",
    "b": "б",
    "c": "с",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "х",
    "i": "и",
    "j": "дж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "к",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "кс",
    "y": "и",
    "z": "з",
}


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

        ``query`` is the original user question. Lexical/FTS tokenises this
        string for process/follow-up queries so conversation history cannot
        flip AND/OR or inject assistant terms into ``to_tsquery``.
        Definition lookups tokenise the extracted lookup term instead.

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
        definition_candidate = False
        definition_score: float | None = None
        definition_signals = ""
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

            # FTS never uses embedding_query. Process/follow-up queries tokenise
            # the original question. Definition lookups tokenise lookup_term so
            # question words (что / такое) cannot fill the lexical slot.
            lookup_term = _definition_lookup_term(normalized)
            embed_texts = [embed_text]
            # Extra vector search embeds only the folded identifier, never a
            # transliteration of the full natural-language question.
            folded_identifier = _folded_entity_embed_text(lookup_term)
            if (
                folded_identifier is not None
                and folded_identifier.casefold() != embed_text.casefold()
            ):
                embed_texts.append(folded_identifier)
            vectors = await provider.embed_batch(embed_texts)
            if len(vectors) != len(embed_texts):
                raise ValidationError(
                    "embedding count mismatch: expected "
                    f"{len(embed_texts)}, got {len(vectors)}"
                )
            for vector in vectors:
                if len(vector) != KB_CHUNK_VECTOR_DIMENSION:
                    raise ValidationError(
                        "embedding dimension mismatch: expected "
                        f"{KB_CHUNK_VECTOR_DIMENSION}, got {len(vector)}"
                    )

            overfetch = min(
                MAX_RETRIEVAL_CANDIDATES,
                max(resolved_top_k * MAX_CHUNKS_PER_ARTICLE_RESULT, resolved_top_k),
            )
            fts_text = lookup_term if lookup_term is not None else normalized
            tsquery = _build_tsquery(
                fts_text, script_variants=lookup_term is not None
            )

            async with self._uow_factory() as uow:
                await uow.enter_tenant(actor_company_id)
                repo = uow.knowledge_article_chunks
                vector_groups = [
                    await repo.search_similar_current_published(
                        allowed_article_ids=allowed_ids,
                        query_embedding=vector,
                        limit=overfetch,
                    )
                    for vector in vectors
                ]
                vector_rows = _union_vector_rows(vector_groups)
                lexical_rows = []
                if tsquery:
                    lexical_rows = await repo.search_lexical_current_published(
                        allowed_article_ids=allowed_ids,
                        tsquery_text=tsquery,
                        limit=LEXICAL_OVERFETCH,
                    )

            vector_candidates = len(vector_rows)
            lexical_candidates = len(lexical_rows)

            merge_debug: dict[str, object] = {}
            hits = _merge_and_score(
                vector_rows=vector_rows,
                lexical_rows=lexical_rows,
                top_k=resolved_top_k,
                min_score=min_score,
                query=normalized,
                debug=merge_debug,
            )
            definition_candidate = bool(merge_debug.get("definition_candidate"))
            raw_score = merge_debug.get("definition_score")
            definition_score = (
                float(raw_score) if isinstance(raw_score, int | float) else None
            )
            raw_signals = merge_debug.get("definition_signals")
            if isinstance(raw_signals, str):
                definition_signals = raw_signals
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
                definition_candidate=definition_candidate,
                definition_score=definition_score,
                definition_signals=definition_signals,
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


def _build_tsquery(query: str, *, script_variants: bool = False) -> str | None:
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

    ``script_variants`` ORs a Latin↔Cyrillic fold of each token so a
    standalone identifier typed in the other script can still match. Default
    is off so existing exact tsquery tests stay unchanged.

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
    terms: list[str] = []
    for token in tokens:
        primary = _tsquery_term(token, prefix_tokens=prefix_tokens)
        if script_variants:
            alt = _script_variant_token(token)
            if alt is not None:
                alt_prefix = prefix_tokens if token in prefix_tokens else frozenset()
                alt_term = _tsquery_term(alt, prefix_tokens=alt_prefix)
                if token in prefix_tokens and ":*" not in alt_term:
                    alt_term = f"{alt}:*"
                terms.append(f"({primary} | {alt_term})")
                continue
        terms.append(primary)
    operator = " & " if len(tokens) <= 3 else " | "
    return operator.join(terms)


def _script_variant_token(token: str) -> str | None:
    """Other-script form of a single-script alphanumeric token, or None."""
    lowered = token.lower()
    has_cyr = bool(_CYRILLIC_RE.search(lowered))
    has_lat = bool(re.search(r"[a-z]", lowered))
    if has_cyr and has_lat:
        return None
    if has_cyr:
        alt = "".join(_CYR_TO_LAT.get(ch, ch) for ch in lowered)
    elif has_lat:
        alt = "".join(_LAT_TO_CYR.get(ch, ch) for ch in lowered)
    else:
        return None
    alt = "".join(ch for ch in alt.lower() if ch.isalnum())
    if len(alt) <= 1 or alt == lowered:
        return None
    if not _TOKEN_RE.fullmatch(alt):
        return None
    return alt


def _folded_entity_embed_text(term: str | None) -> str | None:
    """Other-script identifier to embed in addition to the original query.

    Applies the same per-token Latin↔Cyrillic fold used by FTS. Returns
    None when ``term`` is missing or no token has a script variant, so
    process questions never get whole-query transliteration.
    """
    if not term:
        return None
    tokens = [token.lower() for token in _TOKEN_RE.findall(term) if len(token) > 1]
    if not tokens:
        return None
    folded: list[str] = []
    changed = False
    for token in tokens:
        alt = _script_variant_token(token)
        if alt is not None:
            folded.append(alt)
            changed = True
        else:
            folded.append(token)
    if not changed:
        return None
    return folded[0] if len(folded) == 1 else " ".join(folded)


def _union_vector_rows(
    row_lists: list[list[tuple[KnowledgeArticleChunk, float, str]]],
) -> list[tuple[KnowledgeArticleChunk, float, str]]:
    """Deduplicate vector hits by chunk_id, keeping the lowest cosine distance."""
    best: dict[UUID, tuple[KnowledgeArticleChunk, float, str]] = {}
    for rows in row_lists:
        for chunk, distance, title in rows:
            current = best.get(chunk.id)
            if current is None or distance < current[1]:
                best[chunk.id] = (chunk, distance, title)
    return list(best.values())


def _fold_scripts(text: str) -> str:
    """Casefold and map Cyrillic letters to Latin so identifiers can match."""
    return "".join(_CYR_TO_LAT.get(ch, ch) for ch in text.casefold())


def _normalize_dashes(text: str) -> str:
    return _DASH_RE.sub("-", text)


def _definition_lookup_term(query: str) -> str | None:
    """Entity term when ``query`` is a definition lookup; otherwise None.

    Returns a term for:
    * standalone identifiers (CRM, PROJECT-X, AI-ассистент)
    * explicit definition questions (Что такое CRM?, What is X?)

    Follow-ups, process questions, and long natural-language queries return
    None so existing hybrid / expansion behavior is unchanged.
    """
    stripped = query.strip()
    if not stripped:
        return None
    prefix = _DEFINITION_PREFIX_RE.match(stripped)
    if prefix is not None:
        remainder = stripped[prefix.end() :].strip().strip(_QUERY_PUNCT).strip()
        words = [part for part in remainder.split() if part]
        if 1 <= len(words) <= _MAX_ENTITY_QUERY_WORDS:
            return remainder
        return None
    return stripped if _is_standalone_entity_query(stripped) else None


def _is_standalone_entity_query(query: str) -> bool:
    """True for a short identifier/name, not a follow-up or process question."""
    cleaned = query.strip().strip(_QUERY_PUNCT).strip()
    if not cleaned:
        return False
    words = [part.strip(_QUERY_PUNCT) for part in cleaned.split()]
    words = [part for part in words if part]
    if not words or len(words) > _MAX_ENTITY_QUERY_WORDS:
        return False
    if words[0].casefold() in _FOLLOW_UP_HEADS:
        return False
    if any(part.casefold() in _FUNCTION_WORDS for part in words):
        return False
    return all(_TOKEN_RE.search(part) for part in words)


def _entity_needles(term: str) -> tuple[str, ...]:
    dashed = _normalize_dashes(term).casefold().strip()
    if not dashed:
        return ()
    needles = {dashed, dashed.replace("-", " "), dashed.replace("-", "")}
    folded = _fold_scripts(dashed)
    needles.add(folded)
    needles.add(folded.replace("-", " "))
    needles.add(folded.replace("-", ""))
    return tuple(n for n in needles if len(n) > 1)


def _term_in_text(term: str, text: str) -> bool:
    if len(term) <= 2:
        pattern = rf"(?<![a-zа-яё0-9]){re.escape(term)}(?![a-zа-яё0-9])"
        return re.search(pattern, text, re.IGNORECASE | re.UNICODE) is not None
    return term in text


def _any_needle_in(text: str, needles: tuple[str, ...]) -> bool:
    folded = _fold_scripts(text)
    for needle in needles:
        if _term_in_text(needle, text) or _term_in_text(_fold_scripts(needle), folded):
            return True
    return False


def _first_term_pos(text: str, needles: tuple[str, ...]) -> int | None:
    positions: list[int] = []
    folded = _fold_scripts(text)
    for needle in needles:
        idx = text.find(needle)
        if idx >= 0:
            positions.append(idx)
        folded_needle = _fold_scripts(needle)
        folded_idx = folded.find(folded_needle)
        if folded_idx >= 0:
            positions.append(folded_idx)
    return min(positions) if positions else None


@dataclass(frozen=True, slots=True)
class _StructuredEntity:
    entity_type: str
    canonical_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _StructuredMatch:
    exact: bool
    entity_type: str


def _is_entity_id(value: str) -> bool:
    return bool(_ENTITY_ID_RE.fullmatch(value.strip()))


def _normalize_entity_label(value: str) -> str:
    return _fold_scripts(_normalize_dashes(value).casefold()).strip()


def _entity_label_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        _fold_scripts(token.casefold())
        for token in _TOKEN_RE.findall(_normalize_dashes(value))
        if token
    )


def _split_aliases(raw: str) -> tuple[str, ...]:
    parts: list[str] = []
    for piece in raw.replace(",", ";").split(";"):
        label = piece.strip().strip("`").strip()
        if not label or label in {"—", "-", "–"}:
            continue
        parts.append(label)
    return tuple(parts)


def _iter_structured_entities(body: str) -> tuple[_StructuredEntity, ...]:
    """Parse ENTITY records from chunk text. Does not read chunk.metadata."""
    if not body.strip():
        return ()
    headers = list(_ENTITY_HEADER_RE.finditer(body))
    spans: list[tuple[str, str]] = []
    if headers:
        for index, match in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(body)
            spans.append((match.group(1).strip(), body[match.start() : end]))
    else:
        spans.append(("", body))

    records: list[_StructuredEntity] = []
    for header_name, block in spans:
        fields: dict[str, str] = {}
        for field in _ENTITY_FIELD_RE.finditer(block):
            fields[field.group(1).casefold()] = field.group(2).strip().strip("`").strip()
        canonical = fields.get("canonical_name", "")
        aliases = _split_aliases(fields.get("aliases", ""))
        header_is_id = bool(header_name) and _is_entity_id(header_name)
        if not canonical and header_name and not header_is_id:
            canonical = header_name
        if not canonical and not aliases:
            continue
        records.append(
            _StructuredEntity(
                entity_type=fields.get("entity_type", "").strip().upper(),
                canonical_name=canonical,
                aliases=aliases,
            )
        )
    return tuple(records)


def _label_match_kind(
    label: str, needles: tuple[str, ...]
) -> str | None:
    """Return ``exact`` (full label), ``token``, or None."""
    if not label or not needles:
        return None
    normalized = _normalize_entity_label(label)
    if any(needle == normalized for needle in needles):
        return "exact"
    tokens = _entity_label_tokens(label)
    if any(needle == token for needle in needles for token in tokens):
        return "token"
    return None


def _best_structured_entity_match(
    body: str, needles: tuple[str, ...]
) -> _StructuredMatch | None:
    """Best name/alias match in ``body``. ENTITY IDs never match."""
    if not needles:
        return None
    best: _StructuredMatch | None = None
    best_key: tuple[int, int] = (-1, -1)
    for record in _iter_structured_entities(body):
        kinds: list[str] = []
        if record.canonical_name:
            kind = _label_match_kind(record.canonical_name, needles)
            if kind is not None:
                kinds.append(kind)
        for alias in record.aliases:
            kind = _label_match_kind(alias, needles)
            if kind is not None:
                kinds.append(kind)
        if not kinds:
            continue
        exact = "exact" in kinds
        key = (1 if exact else 0, _ENTITY_TYPE_RANK.get(record.entity_type, 0))
        if key > best_key:
            best_key = key
            best = _StructuredMatch(exact=exact, entity_type=record.entity_type)
    return best


def _has_aliases_decl(content_fold: str, needles: tuple[str, ...]) -> bool:
    for line in content_fold.splitlines():
        if re.search(r"aliases\s*:", line) is None:
            continue
        if _any_needle_in(line, needles):
            return True
    return False


def _has_definition_copula(content_fold: str, needles: tuple[str, ...]) -> bool:
    folded = _fold_scripts(content_fold)
    search_pairs = [(content_fold, needles)]
    folded_needles = tuple(_fold_scripts(n) for n in needles if len(_fold_scripts(n)) > 1)
    if folded_needles:
        search_pairs.append((folded, folded_needles))
    for text, terms in search_pairs:
        for needle in terms:
            for match in re.finditer(re.escape(needle), text):
                tail = text[match.end() : match.end() + 48]
                if _COPULA_AFTER_RE.match(tail):
                    return True
                head = text[max(0, match.start() - 16) : match.start()]
                if _COPULA_BEFORE_RE.search(head):
                    return True
    return False


def _content_without_title_prefix(content: str, title: str) -> str:
    """Return chunk body with a synthetic article-title prefix removed.

    Scoring-only: stored chunk text is never modified. Matches the exact
    ``"{title}\\n\\n"`` prefix written by chunking, or a first-line title.
    """
    title = title.strip()
    if not title:
        return content
    prefix = f"{title}\n\n"
    if content.startswith(prefix):
        return content[len(prefix) :]
    first, _, rest = content.partition("\n")
    if first.strip() == title:
        return rest.lstrip("\n")
    return content


def _score_definition_candidate(
    term: str, content: str, title: str
) -> tuple[float, tuple[str, ...]]:
    """Score how much ``content`` looks like a definition of ``term``.

    Returns ``(0.0, ())`` when the chunk is not a definition candidate.
    Operates on one already-retrieved candidate; never scans the full KB.

    Definition signals (except ``title_match``) are scored on the body after
    stripping a synthetic article-title prefix, so the prefix cannot make
    every chunk of an article look like a definition of the title term.
    """
    if not content or not term:
        return 0.0, ()
    body = _content_without_title_prefix(content, title)
    content_norm = _normalize_dashes(body)
    term_norm = _normalize_dashes(term.strip())
    content_fold = content_norm.casefold()
    title_fold = _normalize_dashes(title).casefold() if title else ""
    needles = _entity_needles(term_norm)
    structured = _best_structured_entity_match(body, needles)
    if not needles:
        return 0.0, ()
    if structured is None and not _any_needle_in(content_fold, needles):
        return 0.0, ()

    signals: list[str] = ["exact_match"]
    score = 1.0
    first_line = content_norm.splitlines()[0].strip() if content_norm else ""
    first_sentence = re.split(r"[\n.]", content_norm, maxsplit=1)[0].strip()

    if structured is not None:
        score += 8.0
        signals.append("structured_entity")
        if structured.exact:
            signals.append("structured_exact")
        if structured.entity_type:
            signals.append(f"structured_type:{structured.entity_type}")
    if _has_aliases_decl(content_fold, needles):
        score += 3.0
        signals.append("aliases")
    if _has_definition_copula(content_fold, needles):
        score += 4.0
        signals.append("definition_copula")

    heading_source = first_line if first_line else first_sentence
    if first_sentence and len(first_sentence) <= 80:
        heading_source = first_sentence
    heading_ok = (
        bool(heading_source)
        and len(heading_source) <= 80
        and _any_needle_in(heading_source.casefold(), needles)
        and _USAGE_RE.search(heading_source) is None
    )
    if heading_ok or heading_source.lstrip().startswith("#"):
        if _any_needle_in(heading_source.casefold(), needles):
            score += 3.0
            signals.append("heading")

    lead_line = next((ln.strip() for ln in content_norm.splitlines() if ln.strip()), "")
    if lead_line.startswith("#") and _any_needle_in(lead_line.casefold(), needles):
        score += 6.0
        signals.append("lead_heading")

    pos = _first_term_pos(content_fold, needles)
    if pos is not None and pos <= 80:
        score += 1.5
        signals.append("term_at_start")
    if _CANONICAL_RE.search(content_fold[:500]):
        score += 2.0
        signals.append("canonical_language")
    if title_fold and _any_needle_in(title_fold, needles):
        score += 1.0
        signals.append("title_match")

    strong = {
        "structured_entity",
        "aliases",
        "definition_copula",
        "heading",
        "lead_heading",
    }
    if not strong.intersection(signals):
        return 0.0, ()
    if score < _MIN_DEFINITION_SCORE:
        return 0.0, ()
    return score, tuple(signals)


def _reserved_definition_chunks(
    sorted_pool: list[tuple[KnowledgeArticleChunk, float, str, float | None]],
    *,
    query: str | None,
    min_score: float | None,
) -> list[tuple[KnowledgeArticleChunk, float, str, float, tuple[str, ...]]]:
    """Best definition-like exact match, up to ``DEFINITION_RESERVED`` globally.

    Only runs for standalone entity / definition questions. Candidates come
    from the existing hybrid pool (vector + FTS overfetch), not a full scan.
    """
    term = _definition_lookup_term(query) if query else None
    if term is None:
        return []

    ranked: list[
        tuple[int, int, int, float, float, KnowledgeArticleChunk, str, tuple[str, ...]]
    ] = []
    needles = _entity_needles(_normalize_dashes(term.strip()))
    for chunk, score, title, _lex_rank in sorted_pool:
        if min_score is not None and score < min_score:
            continue
        def_score, signals = _score_definition_candidate(term, chunk.content, title)
        if def_score <= 0.0:
            continue
        body = _content_without_title_prefix(chunk.content, title)
        structured = _best_structured_entity_match(body, needles)
        ranked.append(
            (
                1 if structured is not None else 0,
                1 if structured is not None and structured.exact else 0,
                (
                    _ENTITY_TYPE_RANK.get(structured.entity_type, 0)
                    if structured is not None
                    else 0
                ),
                def_score,
                score,
                chunk,
                title,
                signals,
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]), reverse=True)

    reserved: list[tuple[KnowledgeArticleChunk, float, str, float, tuple[str, ...]]] = []
    for (
        _has_struct,
        _exact,
        _type_rank,
        def_score,
        score,
        chunk,
        title,
        signals,
    ) in ranked[:DEFINITION_RESERVED]:
        reserved.append((chunk, score, title, def_score, signals))
    return reserved


def _merge_and_score(
    *,
    vector_rows: list[tuple[KnowledgeArticleChunk, float, str]],
    lexical_rows: list[tuple[KnowledgeArticleChunk, float, str]],
    top_k: int,
    min_score: float | None,
    query: str | None = None,
    debug: dict[str, object] | None = None,
) -> list[RetrievalHit]:
    """Merge vector and lexical candidates, assign hybrid scores, deduplicate.

    Scoring rules (see module docstring for rationale):
    * Vector-only:       ``final_score = clamp(1 - distance, 0, 1)``
    * Vector + lexical:  ``final_score = vector_score + LEXICAL_BOOST``
    * Lexical-only:      ``final_score = LEXICAL_FLOOR_SCORE``

    The ``ts_rank_cd`` value from lexical rows is not added to the cosine
    scale. It selects the per-article reserved FTS slot in
    ``_dedupe_and_score``.

    After scoring, the pool is sorted descending by ``final_score``. For
    standalone entity / definition questions a definition candidate is
    reserved first (original hybrid score, no inflation). Then
    ``LEXICAL_RESERVED_PER_ARTICLE`` FTS slots, the per-article cap, and
    ``top_k`` are applied.
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
    return _dedupe_and_score(
        sorted_pool,
        top_k=top_k,
        min_score=min_score,
        query=query,
        debug=debug,
    )


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
    definition_candidate: bool = False,
    definition_score: float | None = None,
    definition_signals: str = "",
) -> None:
    """Operational retrieve log. Never include query, body, embeddings, or secrets."""
    logger.info(
        "kb_retrieve request_id=%s company_id=%s employee_id=%s actor_role=%s "
        "allowed_articles=%s vector_candidates=%s lexical_candidates=%s "
        "hit_count=%s top_k=%s result=%s duration_ms=%.1f "
        "definition_candidate=%s definition_score=%s definition_signals=%s",
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
        str(definition_candidate).lower(),
        f"{definition_score:.2f}" if definition_score is not None else "",
        definition_signals,
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
    query: str | None = None,
    debug: dict[str, object] | None = None,
) -> list[RetrievalHit]:
    """Reserve definition + FTS slots, then apply per-article cap and top_k.

    ``sorted_pool`` must already be sorted descending by final hybrid score.
    Queries with no lexical hits keep score-order ranking unchanged.
    Definition reservation does not change hybrid scores.
    """
    seen_ids: set[UUID] = set()
    seen_article: dict[UUID, int] = {}
    hits: list[RetrievalHit] = []

    for chunk, score, title, def_score, signals in _reserved_definition_chunks(
        sorted_pool, query=query, min_score=min_score
    ):
        if len(hits) >= top_k:
            break
        used = seen_article.get(chunk.article_id, 0)
        if used >= MAX_CHUNKS_PER_ARTICLE_RESULT:
            continue
        seen_ids.add(chunk.id)
        seen_article[chunk.article_id] = used + 1
        hits.append(_hit_from_pool(chunk, score, title))
        if debug is not None:
            debug["definition_candidate"] = True
            debug["definition_score"] = def_score
            debug["definition_signals"] = ",".join(signals)
            debug["exact_match"] = "exact_match" in signals

    for chunk, score, title in _reserved_lexical_chunks(
        sorted_pool, min_score=min_score
    ):
        if len(hits) >= top_k:
            break
        if chunk.id in seen_ids:
            continue
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
