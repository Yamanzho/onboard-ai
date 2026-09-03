"""Index a current published KB version into pgvector chunks.

Vector rows are derived data, not ACL authority and not a second source of
truth. ArticleService (publication, visibility, program ACL) remains the
authority. This service only refuses unpublished / foreign / non-current rows.

AI-3 transaction contract
-------------------------
Indexing is **synchronous and post-commit**. The KB write (publish / new
published version) commits in its own UnitOfWork first. This indexer then
opens a **separate** UoW. If embedding or chunk writes fail:

- the exception is logged and re-raised (never swallowed);
- the caller must not report success;
- the already-committed published article is left intact;
- this method's UoW rolls back, so no partial chunk set is committed.

There is no background queue. See ``docs/ai/architecture.md``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION, MAX_CHUNK_CHARS_SAFE
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.metrics import KB_INDEX_RUNS
from app.db.enums import (
    EmployeeRole,
    KnowledgeArticleStatus,
    KnowledgeIndexStatus,
    KnowledgeLinkTargetType,
    PlatformRole,
)
from app.db.models.knowledge_article_chunk import KnowledgeArticleChunk
from app.db.uow import UnitOfWork
from app.services.ai.chunking import chunk_article
from app.services.ai.embedding_identity import embedding_identity_from_provider
from app.services.ai.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.tenancy import ensure_same_company

logger = logging.getLogger("app.kb.index")

# Explicit: this service is not enlisted in the ArticleService publish transaction.
INDEXING_RUNS_AFTER_KB_COMMIT = True
_ARTICLE_LIST_PAGE = 1000

# OpenAI accepts up to 2048 items per /v1/embeddings call but practical latency
# degrades for very large batches. Use sub-batches of 100 for large articles
# (~100-160 chunks for 140k-200k char articles) to keep individual API calls
# fast and avoid timeout risk.
_EMBED_BATCH_SIZE = 100
_INDEX_LEASE_SECONDS = 300
_KB_MANAGEMENT_ROLES = frozenset(
    {
        EmployeeRole.ADMIN.value,
        EmployeeRole.HR.value,
    }
)


@dataclass(frozen=True, slots=True)
class CorpusReindexItemResult:
    article_id: UUID
    version_id: UUID
    status: Literal["indexed", "failed"]
    indexed_chunks: int = 0
    failure_category: str | None = None


@dataclass(frozen=True, slots=True)
class CorpusReindexResult:
    """Structured per-version corpus result. Not an ACL grant."""

    attempted_articles: int
    succeeded_articles: int
    failed_articles: int
    indexed_chunks: int
    items: tuple[CorpusReindexItemResult, ...]

    @property
    def indexed_articles(self) -> int:
        """Compatibility alias for callers that used the old success count."""
        return self.succeeded_articles

    @property
    def complete(self) -> bool:
        return self.failed_articles == 0


class KnowledgeChunkIndexer:
    """Internal indexer: published current version → chunks + fake embeddings."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._embedding_provider = embedding_provider

    def _provider(self) -> EmbeddingProvider:
        return self._embedding_provider or get_embedding_provider()

    async def index_published_version(
        self,
        *,
        actor_company_id: UUID,
        article_id: UUID,
        version_id: UUID,
        company_id: UUID | None = None,
    ) -> list[KnowledgeArticleChunk]:
        """Replace chunks for ``version_id`` only. Older versions stay intact.

        ``actor_company_id`` is the authenticated tenant (JWT / ``BOT_COMPANY_ID``)
        and is the **only** value used for ``enter_tenant``. ``company_id`` is an
        untrusted claimed tenant (query/body). A mismatch is not-found, never a
        tenant switch.
        """
        started = time.perf_counter()
        try:
            stored = await self._index_published_version(
                actor_company_id=actor_company_id,
                article_id=article_id,
                version_id=version_id,
                company_id=company_id,
            )
        except (NotFoundError, ValidationError):
            KB_INDEX_RUNS.labels(result="rejected", error_category="validation").inc()
            logger.info(
                "kb_index_rejected company_id=%s article_id=%s version_id=%s "
                "result=rejected duration_ms=%.1f",
                actor_company_id,
                article_id,
                version_id,
                (time.perf_counter() - started) * 1000,
            )
            raise
        except Exception as exc:
            KB_INDEX_RUNS.labels(
                result="error",
                error_category=_failure_category(exc),
            ).inc()
            logger.exception(
                "kb_index_failed company_id=%s article_id=%s version_id=%s "
                "result=error duration_ms=%.1f",
                actor_company_id,
                article_id,
                version_id,
                (time.perf_counter() - started) * 1000,
            )
            raise

        KB_INDEX_RUNS.labels(result="success", error_category="none").inc()
        logger.info(
            "kb_index_ok company_id=%s article_id=%s version_id=%s "
            "chunk_count=%s result=success duration_ms=%.1f",
            actor_company_id,
            article_id,
            version_id,
            len(stored),
            (time.perf_counter() - started) * 1000,
        )
        return stored

    async def _index_published_version(
        self,
        *,
        actor_company_id: UUID,
        article_id: UUID,
        version_id: UUID,
        company_id: UUID | None,
    ) -> list[KnowledgeArticleChunk]:
        owner_token = uuid4()
        had_active_index = False
        claimed = False
        try:
            had_active_index = await self._claim_indexing(
                actor_company_id=actor_company_id,
                article_id=article_id,
                version_id=version_id,
                company_id=company_id,
                owner_token=owner_token,
            )
            claimed = True
            texts, metadata = await self._prepare_chunks(
                actor_company_id=actor_company_id,
                article_id=article_id,
                version_id=version_id,
            )
            provider = self._provider()
            if provider.dimension != KB_CHUNK_VECTOR_DIMENSION:
                raise ValidationError(
                    "embedding dimension mismatch: provider="
                    f"{provider.dimension}, column={KB_CHUNK_VECTOR_DIMENSION}"
                )
            embeddings = await self._embed_all(
                provider=provider,
                texts=texts,
                actor_company_id=actor_company_id,
                article_id=article_id,
                version_id=version_id,
                owner_token=owner_token,
            )
            identity = embedding_identity_from_provider(provider)
            return await self._finalize_index(
                actor_company_id=actor_company_id,
                article_id=article_id,
                version_id=version_id,
                owner_token=owner_token,
                texts=texts,
                embeddings=embeddings,
                metadata={
                    **metadata,
                    "embedding_provider": identity.provider,
                    "embedding_model": identity.model,
                },
                embedding_provider=identity.provider,
                embedding_model=identity.model,
                embedding_dimension=identity.dimension,
            )
        except Exception as exc:
            if claimed:
                try:
                    await self._record_failure(
                        actor_company_id=actor_company_id,
                        version_id=version_id,
                        owner_token=owner_token,
                        had_active_index=had_active_index,
                        failure_category=_failure_category(exc),
                    )
                except Exception:
                    logger.exception(
                        "kb_index_failure_state_write_failed company_id=%s "
                        "article_id=%s version_id=%s",
                        actor_company_id,
                        article_id,
                        version_id,
                    )
            raise

    async def _claim_indexing(
        self,
        *,
        actor_company_id: UUID,
        article_id: UUID,
        version_id: UUID,
        company_id: UUID | None,
        owner_token: UUID,
    ) -> bool:
        not_found = f"Knowledge article {article_id} not found"
        if company_id is not None:
            ensure_same_company(
                resource_company_id=company_id,
                actor_company_id=actor_company_id,
                not_found_message=not_found,
            )
        async with self._uow_factory() as uow:
            await uow.enter_tenant(actor_company_id)
            article = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            if article is None:
                raise NotFoundError(not_found)
            ensure_same_company(
                resource_company_id=article.company_id,
                actor_company_id=actor_company_id,
                not_found_message=not_found,
            )

            if article.status != KnowledgeArticleStatus.PUBLISHED.value:
                raise ValidationError(
                    f"Only a published article can be indexed (status={article.status!r})"
                )
            if article.current_version_id is None:
                raise ValidationError(
                    f"Cannot index article {article_id} without a current version"
                )
            if article.current_version_id != version_id:
                raise ValidationError(
                    "version_id is not the current published version of this article"
                )

            version = await uow.knowledge_article_versions.get_by_id(version_id)
            if version is None:
                raise NotFoundError(f"Knowledge article version {version_id} not found")
            ensure_same_company(
                resource_company_id=version.company_id,
                actor_company_id=actor_company_id,
                not_found_message=f"Knowledge article version {version_id} not found",
            )
            if version.article_id != article_id:
                raise NotFoundError(f"Knowledge article version {version_id} not found")

            claimed = await uow.knowledge_article_versions.claim_indexing(
                version_id,
                owner_token=owner_token,
                lease_seconds=_INDEX_LEASE_SECONDS,
            )
            if claimed is None:
                raise ConflictError(f"Knowledge article version {version_id} is already indexing")
            had_active_index = claimed.index_status == KnowledgeIndexStatus.INDEXED.value
            await uow.commit()
            return had_active_index

    async def _prepare_chunks(
        self,
        *,
        actor_company_id: UUID,
        article_id: UUID,
        version_id: UUID,
    ) -> tuple[list[str], dict[str, Any]]:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(actor_company_id)
            article = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            if (
                article is None
                or article.status != KnowledgeArticleStatus.PUBLISHED.value
                or article.current_version_id != version_id
            ):
                raise ValidationError("Article is no longer published at this version")
            version = await uow.knowledge_article_versions.get_by_id(version_id)
            if version is None or version.article_id != article_id:
                raise NotFoundError(f"Knowledge article version {version_id} not found")
            body_char_count = len(version.body or "")
            texts = chunk_article(
                title=version.title,
                body=version.body,
                body_format=version.body_format,
            )
            if not texts:
                raise ValidationError("nothing to index: empty title and body")

            logger.info(
                "kb_index_chunked company_id=%s article_id=%s version_id=%s "
                "body_chars=%d chunk_count=%d",
                actor_company_id,
                article_id,
                version_id,
                body_char_count,
                len(texts),
            )

            # Pre-flight: every chunk must be within the safe character limit
            # before we send anything to the embedding provider.
            for chunk_idx, chunk_text in enumerate(texts):
                if len(chunk_text) > MAX_CHUNK_CHARS_SAFE:
                    raise ValidationError(
                        f"chunk {chunk_idx} exceeds safe embedding character limit: "
                        f"{len(chunk_text)} chars (max {MAX_CHUNK_CHARS_SAFE}). "
                        f"article_id={article_id} version_id={version_id}"
                    )
            return texts, _chunk_metadata(article)

    async def _embed_all(
        self,
        *,
        provider: EmbeddingProvider,
        texts: list[str],
        actor_company_id: UUID,
        article_id: UUID,
        version_id: UUID,
        owner_token: UUID,
    ) -> list[list[float]]:
        embeddings: list[list[float]] = []
        batch_count = 0
        for batch_start in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = texts[batch_start : batch_start + _EMBED_BATCH_SIZE]
            embeddings.extend(await provider.embed_batch(batch))
            await self._renew_lease(
                actor_company_id=actor_company_id,
                version_id=version_id,
                owner_token=owner_token,
            )
            batch_count += 1
        logger.info(
            "kb_index_embedded company_id=%s article_id=%s version_id=%s "
            "chunk_count=%d embed_batches=%d",
            actor_company_id,
            article_id,
            version_id,
            len(texts),
            batch_count,
        )
        if len(embeddings) != len(texts):
            raise ValidationError("embedding batch size does not match chunks")
        for vector in embeddings:
            if len(vector) != KB_CHUNK_VECTOR_DIMENSION:
                raise ValidationError(
                    "embedding dimension mismatch: expected "
                    f"{KB_CHUNK_VECTOR_DIMENSION}, got {len(vector)}"
                )
        return embeddings

    async def _renew_lease(
        self,
        *,
        actor_company_id: UUID,
        version_id: UUID,
        owner_token: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(actor_company_id)
            renewed = await uow.knowledge_article_versions.renew_indexing_lease(
                version_id,
                owner_token=owner_token,
                lease_seconds=_INDEX_LEASE_SECONDS,
            )
            if not renewed:
                raise ConflictError("Indexing lease expired or changed owner")
            await uow.commit()

    async def _finalize_index(
        self,
        *,
        actor_company_id: UUID,
        article_id: UUID,
        version_id: UUID,
        owner_token: UUID,
        texts: list[str],
        embeddings: list[list[float]],
        metadata: dict[str, Any],
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
    ) -> list[KnowledgeArticleChunk]:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(actor_company_id)
            article = await uow.knowledge_articles.get_by_id(article_id)
            if (
                article is None
                or article.status != KnowledgeArticleStatus.PUBLISHED.value
                or article.current_version_id != version_id
            ):
                raise ValidationError("Article is no longer published at this version")
            version = await uow.knowledge_article_versions.get_claim_for_update(
                version_id,
                owner_token=owner_token,
            )
            if version is None:
                raise ConflictError("Indexing lease expired or changed owner")

            await uow.knowledge_article_chunks.delete_by_version_id(version_id)
            stored: list[KnowledgeArticleChunk] = []
            for index, (content, embedding) in enumerate(zip(texts, embeddings, strict=True)):
                row = KnowledgeArticleChunk(
                    company_id=actor_company_id,
                    article_id=article_id,
                    version_id=version_id,
                    chunk_index=index,
                    content=content,
                    embedding=list(embedding),
                    extra={**metadata, "chunk_index": index},
                )
                stored.append(await uow.knowledge_article_chunks.create(row))

            await uow.session.flush()
            persisted = await uow.knowledge_article_chunks.list_by_version_id(version_id)
            if len(persisted) != len(texts) or [row.chunk_index for row in persisted] != list(
                range(len(texts))
            ):
                raise ValidationError("persisted chunk set is incomplete")
            now = datetime.now(UTC)
            version.index_status = KnowledgeIndexStatus.INDEXED.value
            version.embedding_provider = embedding_provider
            version.embedding_model = embedding_model
            version.embedding_dimension = embedding_dimension
            version.indexed_chunk_count = len(stored)
            version.indexed_at = now
            version.indexing_failed_at = None
            version.failure_category = None
            version.indexing_owner_token = None
            version.indexing_lease_expires_at = None
            await uow.commit()
            return stored

    async def _record_failure(
        self,
        *,
        actor_company_id: UUID,
        version_id: UUID,
        owner_token: UUID,
        had_active_index: bool,
        failure_category: str,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(actor_company_id)
            version = await uow.knowledge_article_versions.get_by_id_for_update(version_id)
            if version is None or version.indexing_owner_token != owner_token:
                return
            version.index_status = (
                KnowledgeIndexStatus.INDEXED.value
                if had_active_index
                else KnowledgeIndexStatus.FAILED.value
            )
            version.indexing_failed_at = datetime.now(UTC)
            version.failure_category = failure_category
            version.indexing_owner_token = None
            version.indexing_lease_expires_at = None
            await uow.commit()

    async def reindex_published_corpus(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        claimed_company_id: UUID | None = None,
    ) -> CorpusReindexResult:
        """Rebuild current published chunks for the authenticated tenant only.

        Uses ArticleService to enumerate published articles (HR/Admin). Does not
        change KB ACL. ``claimed_company_id`` is untrusted.
        """
        started = time.perf_counter()
        article_ids: list[tuple[UUID, UUID]] = []
        chunk_count = 0
        items: list[CorpusReindexItemResult] = []
        try:
            if actor_role == PlatformRole.SUPER_ADMIN.value:
                raise ForbiddenError("Super Admin has no AI access without tenant impersonation")
            if actor_role not in _KB_MANAGEMENT_ROLES:
                raise ForbiddenError("HR or Admin role required to reindex the knowledge corpus")
            if claimed_company_id is not None:
                ensure_same_company(
                    resource_company_id=claimed_company_id,
                    actor_company_id=actor_company_id,
                    not_found_message=f"Company {claimed_company_id} not found",
                )

            from app.services.knowledge.article_service import ArticleService

            article_service = ArticleService(uow_factory=self._uow_factory)
            offset = 0
            while True:
                page = await article_service.list_articles(
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
                    article_ids.append((article.id, article.current_version_id))
                if len(page) < _ARTICLE_LIST_PAGE:
                    break
                offset += _ARTICLE_LIST_PAGE

            for article_id, version_id in article_ids:
                try:
                    stored = await self.index_published_version(
                        actor_company_id=actor_company_id,
                        article_id=article_id,
                        version_id=version_id,
                        company_id=actor_company_id,
                    )
                except Exception as exc:
                    items.append(
                        CorpusReindexItemResult(
                            article_id=article_id,
                            version_id=version_id,
                            status="failed",
                            failure_category=_failure_category(exc),
                        )
                    )
                    continue
                chunk_count += len(stored)
                items.append(
                    CorpusReindexItemResult(
                        article_id=article_id,
                        version_id=version_id,
                        status="indexed",
                        indexed_chunks=len(stored),
                    )
                )
        except (ForbiddenError, NotFoundError, ValidationError):
            logger.info(
                "kb_index_corpus company_id=%s actor_role=%s result=rejected duration_ms=%.1f",
                actor_company_id,
                actor_role,
                (time.perf_counter() - started) * 1000,
            )
            raise
        except Exception:
            logger.exception(
                "kb_index_corpus company_id=%s actor_role=%s result=error duration_ms=%.1f",
                actor_company_id,
                actor_role,
                (time.perf_counter() - started) * 1000,
            )
            raise

        result = CorpusReindexResult(
            attempted_articles=len(article_ids),
            succeeded_articles=sum(item.status == "indexed" for item in items),
            failed_articles=sum(item.status == "failed" for item in items),
            indexed_chunks=chunk_count,
            items=tuple(items),
        )
        logger.info(
            "kb_index_corpus company_id=%s actor_role=%s attempted=%s succeeded=%s "
            "failed=%s chunk_count=%s result=%s duration_ms=%.1f",
            actor_company_id,
            actor_role,
            result.attempted_articles,
            result.succeeded_articles,
            result.failed_articles,
            result.indexed_chunks,
            "success" if result.complete else "partial",
            (time.perf_counter() - started) * 1000,
        )
        return result


def _chunk_metadata(article: Any) -> dict[str, Any]:
    """Denormalized retrieval hints. Not an ACL source of truth."""
    program_ids = sorted(
        {
            str(link.target_id)
            for link in (article.links or [])
            if link.target_type == KnowledgeLinkTargetType.PROGRAM.value
        }
    )
    return {
        "visibility": article.visibility,
        "status": article.status,
        "program_ids": program_ids,
        "title": article.current_version.title if article.current_version else None,
        "is_current": True,
    }


def _failure_category(exc: Exception) -> str:
    """Return a bounded, non-sensitive operational category."""
    if isinstance(exc, ServiceUnavailableError):
        return "provider_unavailable"
    if isinstance(exc, ConflictError):
        return "concurrent_attempt"
    if isinstance(exc, NotFoundError):
        return "not_found"
    if isinstance(exc, ValidationError):
        return "validation"
    if "database" in type(exc).__module__.lower() or "sqlalchemy" in type(exc).__module__.lower():
        return "database"
    return "internal"
