from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import KnowledgeArticleStatus
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
            delete(KnowledgeArticleChunk).where(
                KnowledgeArticleChunk.version_id == version_id
            )
        )
        return int(result.rowcount or 0)

    async def search_similar_current_published(
        self,
        *,
        allowed_article_ids: Sequence[UUID],
        query_embedding: Sequence[float],
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
