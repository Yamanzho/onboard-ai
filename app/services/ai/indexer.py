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
from typing import Any
from uuid import UUID

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.db.enums import EmployeeRole, KnowledgeArticleStatus, KnowledgeLinkTargetType, PlatformRole
from app.db.models.knowledge_article_chunk import KnowledgeArticleChunk
from app.db.uow import UnitOfWork
from app.services.ai.chunking import chunk_article
from app.services.ai.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.tenancy import ensure_same_company

logger = logging.getLogger("app.kb.index")

# Explicit: this service is not enlisted in the ArticleService publish transaction.
INDEXING_RUNS_AFTER_KB_COMMIT = True
_ARTICLE_LIST_PAGE = 1000
_KB_MANAGEMENT_ROLES = frozenset(
    {
        EmployeeRole.ADMIN.value,
        EmployeeRole.HR.value,
    }
)


@dataclass(frozen=True, slots=True)
class CorpusReindexResult:
    """Counts for a tenant published-corpus rebuild. Not an ACL grant."""

    indexed_articles: int
    indexed_chunks: int


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
            logger.info(
                "kb_index_rejected company_id=%s article_id=%s version_id=%s "
                "result=rejected duration_ms=%.1f",
                actor_company_id,
                article_id,
                version_id,
                (time.perf_counter() - started) * 1000,
            )
            raise
        except Exception:
            logger.exception(
                "kb_index_failed company_id=%s article_id=%s version_id=%s "
                "result=error duration_ms=%.1f",
                actor_company_id,
                article_id,
                version_id,
                (time.perf_counter() - started) * 1000,
            )
            raise

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
        not_found = f"Knowledge article {article_id} not found"
        if company_id is not None:
            ensure_same_company(
                resource_company_id=company_id,
                actor_company_id=actor_company_id,
                not_found_message=not_found,
            )

        provider = self._provider()
        if provider.dimension != KB_CHUNK_VECTOR_DIMENSION:
            raise ValidationError(
                "embedding dimension mismatch: provider="
                f"{provider.dimension}, column={KB_CHUNK_VECTOR_DIMENSION}"
            )

        async with self._uow_factory() as uow:
            # Authenticated tenant only — never a caller-supplied company_id.
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
                    "Only a published article can be indexed "
                    f"(status={article.status!r})"
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

            texts = chunk_article(
                title=version.title,
                body=version.body,
                body_format=version.body_format,
            )
            if not texts:
                raise ValidationError("nothing to index: empty title and body")

            # Embed before mutating rows so a provider failure cannot leave
            # a deleted-but-unreplaced chunk set (this UoW would roll back
            # anyway; ordering keeps the failure window obvious).
            embeddings = await provider.embed_batch(texts)
            if len(embeddings) != len(texts):
                raise ValidationError("embedding batch size does not match chunks")
            for vector in embeddings:
                if len(vector) != KB_CHUNK_VECTOR_DIMENSION:
                    raise ValidationError(
                        "embedding dimension mismatch: expected "
                        f"{KB_CHUNK_VECTOR_DIMENSION}, got {len(vector)}"
                    )

            metadata = _chunk_metadata(
                article,
                embedding_model=getattr(provider, "model", "unknown"),
            )
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

            await uow.commit()
            return stored

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
        try:
            if actor_role == PlatformRole.SUPER_ADMIN.value:
                raise ForbiddenError(
                    "Super Admin has no AI access without tenant impersonation"
                )
            if actor_role not in _KB_MANAGEMENT_ROLES:
                raise ForbiddenError(
                    "HR or Admin role required to reindex the knowledge corpus"
                )
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
                stored = await self.index_published_version(
                    actor_company_id=actor_company_id,
                    article_id=article_id,
                    version_id=version_id,
                    company_id=actor_company_id,
                )
                chunk_count += len(stored)
        except (ForbiddenError, NotFoundError, ValidationError):
            logger.info(
                "kb_index_corpus company_id=%s actor_role=%s "
                "result=rejected duration_ms=%.1f",
                actor_company_id,
                actor_role,
                (time.perf_counter() - started) * 1000,
            )
            raise
        except Exception:
            logger.exception(
                "kb_index_corpus company_id=%s actor_role=%s "
                "result=error duration_ms=%.1f",
                actor_company_id,
                actor_role,
                (time.perf_counter() - started) * 1000,
            )
            raise

        result = CorpusReindexResult(
            indexed_articles=len(article_ids),
            indexed_chunks=chunk_count,
        )
        logger.info(
            "kb_index_corpus company_id=%s actor_role=%s article_count=%s "
            "chunk_count=%s result=success duration_ms=%.1f",
            actor_company_id,
            actor_role,
            result.indexed_articles,
            result.indexed_chunks,
            (time.perf_counter() - started) * 1000,
        )
        return result


def _chunk_metadata(article: Any, *, embedding_model: str) -> dict[str, Any]:
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
        "embedding_model": embedding_model,
    }
