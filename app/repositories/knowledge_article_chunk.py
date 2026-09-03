from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.enums import KnowledgeArticleStatus, KnowledgeIndexStatus
from app.db.models.knowledge_article import KnowledgeArticle
from app.db.models.knowledge_article_chunk import KnowledgeArticleChunk
from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.repositories.base import BaseRepository


class KnowledgeArticleChunkRepository(BaseRepository[KnowledgeArticleChunk]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeArticleChunk)

    async def list_by_version_id(self, version_id: UUID) -> list[KnowledgeArticleChunk]:
        self._ensure_rls_context()
        stmt = (
            select(KnowledgeArticleChunk)
            .where(KnowledgeArticleChunk.version_id == version_id)
            .order_by(KnowledgeArticleChunk.chunk_index.asc())
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_by_article_id(self, article_id: UUID) -> list[KnowledgeArticleChunk]:
        self._ensure_rls_context()
        stmt = (
            select(KnowledgeArticleChunk)
            .where(KnowledgeArticleChunk.article_id == article_id)
            .order_by(
                KnowledgeArticleChunk.version_id.asc(),
                KnowledgeArticleChunk.chunk_index.asc(),
            )
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def delete_by_version_id(self, version_id: UUID) -> int:
        """Replace-index helper. Does not touch chunks of other versions."""
        self._ensure_rls_context()
        result = await self._session.execute(
            delete(KnowledgeArticleChunk).where(KnowledgeArticleChunk.version_id == version_id)
        )
        return int(result.rowcount or 0)

    async def search_similar_current_published(
        self,
        *,
        allowed_article_ids: Sequence[UUID],
        query_embedding: Sequence[float],
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
        limit: int,
    ) -> list[tuple[KnowledgeArticleChunk, float, str]]:
        """Exact cosine search inside an already-authorized article id set.

        Caller must compute ``allowed_article_ids`` via ArticleService first.
        Historical chunks are excluded by joining live ``current_version_id``.
        Chunk ``metadata`` is not used for authorization.
        """
        self._ensure_rls_context()
        if not allowed_article_ids or limit < 1:
            return []

        counted_chunk = aliased(KnowledgeArticleChunk)
        complete_chunk_count = (
            select(func.count(counted_chunk.id))
            .where(counted_chunk.version_id == KnowledgeArticleVersion.id)
            .correlate(KnowledgeArticleVersion)
            .scalar_subquery()
        )
        distance = KnowledgeArticleChunk.embedding.cosine_distance(list(query_embedding))
        stmt = (
            select(KnowledgeArticleChunk, distance, KnowledgeArticleVersion.title)
            .join(
                KnowledgeArticle,
                KnowledgeArticle.id == KnowledgeArticleChunk.article_id,
            )
            .join(
                KnowledgeArticleVersion,
                KnowledgeArticleVersion.id == KnowledgeArticle.current_version_id,
            )
            .where(KnowledgeArticleChunk.article_id.in_(tuple(allowed_article_ids)))
            .where(KnowledgeArticleChunk.version_id == KnowledgeArticle.current_version_id)
            .where(KnowledgeArticle.status == KnowledgeArticleStatus.PUBLISHED.value)
            .where(KnowledgeArticleVersion.index_status == KnowledgeIndexStatus.INDEXED.value)
            .where(KnowledgeArticleVersion.embedding_provider == embedding_provider)
            .where(KnowledgeArticleVersion.embedding_model == embedding_model)
            .where(KnowledgeArticleVersion.embedding_dimension == embedding_dimension)
            .where(complete_chunk_count == KnowledgeArticleVersion.indexed_chunk_count)
            .order_by(
                distance.asc(),
                KnowledgeArticleChunk.article_id.asc(),
                KnowledgeArticleChunk.chunk_index.asc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows: list[tuple[KnowledgeArticleChunk, float, str]] = []
        for chunk, dist, title in result.all():
            rows.append((chunk, float(dist), str(title)))
        return rows

    async def search_lexical_current_published(
        self,
        *,
        allowed_article_ids: Sequence[UUID],
        tsquery_text: str,
        limit: int,
    ) -> list[tuple[KnowledgeArticleChunk, float, str]]:
        """FTS search over chunk content inside an already-authorized article id set.

        Uses the same ACL guards as ``search_similar_current_published``:
        - ``allowed_article_ids`` computed by ArticleService before this call
        - ``current_version_id`` join excludes historical chunk versions
        - ``status = 'published'`` filter
        - tenant RLS enforced by the session's ``app.company_id`` setting

        The ``tsquery_text`` must already be sanitised (alphanumeric tokens only).
        Never pass raw user input directly.

        Returns ``(chunk, lexical_score, article_title)`` ordered by
        ``ts_rank_cd`` descending.  ``lexical_score`` is a dimensionless float
        in the ``[0, 1]`` range (rank / (rank + 1) normalisation) and is NOT
        comparable to cosine similarity; callers must not add the two scales.
        """
        self._ensure_rls_context()
        if not allowed_article_ids or limit < 1 or not tsquery_text:
            return []

        counted_chunk = aliased(KnowledgeArticleChunk)
        complete_chunk_count = (
            select(func.count(counted_chunk.id))
            .where(counted_chunk.version_id == KnowledgeArticleVersion.id)
            .correlate(KnowledgeArticleVersion)
            .scalar_subquery()
        )
        tsv = func.to_tsvector(text("'simple'"), KnowledgeArticleChunk.content)
        tsq = func.to_tsquery(text("'simple'"), tsquery_text)
        # ts_rank_cd normalisation flag 32 → rank / (rank + 1), bounded 0..1.
        rank = func.ts_rank_cd(tsv, tsq, 32)

        stmt = (
            select(KnowledgeArticleChunk, rank, KnowledgeArticleVersion.title)
            .join(
                KnowledgeArticle,
                KnowledgeArticle.id == KnowledgeArticleChunk.article_id,
            )
            .join(
                KnowledgeArticleVersion,
                KnowledgeArticleVersion.id == KnowledgeArticle.current_version_id,
            )
            .where(KnowledgeArticleChunk.article_id.in_(tuple(allowed_article_ids)))
            .where(KnowledgeArticleChunk.version_id == KnowledgeArticle.current_version_id)
            .where(KnowledgeArticle.status == KnowledgeArticleStatus.PUBLISHED.value)
            .where(KnowledgeArticleVersion.index_status == KnowledgeIndexStatus.INDEXED.value)
            .where(complete_chunk_count == KnowledgeArticleVersion.indexed_chunk_count)
            .where(tsv.op("@@")(tsq))
            .order_by(
                rank.desc(),
                KnowledgeArticleChunk.article_id.asc(),
                KnowledgeArticleChunk.chunk_index.asc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows: list[tuple[KnowledgeArticleChunk, float, str]] = []
        for chunk, lex_score, title in result.all():
            rows.append((chunk, float(lex_score), str(title)))
        return rows
