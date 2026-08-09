from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT


class KnowledgeArticleVersionRepository(BaseRepository[KnowledgeArticleVersion]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeArticleVersion)

    async def list_by_article_id(
        self,
        article_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeArticleVersion]:
        self._ensure_rls_context()
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt = (
            select(KnowledgeArticleVersion)
            .where(KnowledgeArticleVersion.article_id == article_id)
            .order_by(KnowledgeArticleVersion.version.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_by_article_and_version(
        self,
        article_id: UUID,
        version: int,
    ) -> KnowledgeArticleVersion | None:
        self._ensure_rls_context()
        stmt = select(KnowledgeArticleVersion).where(
            KnowledgeArticleVersion.article_id == article_id,
            KnowledgeArticleVersion.version == version,
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def next_version_number(self, article_id: UUID) -> int:
        self._ensure_rls_context()
        stmt = select(func.coalesce(func.max(KnowledgeArticleVersion.version), 0)).where(
            KnowledgeArticleVersion.article_id == article_id,
        )
        current = await self._session.scalar(stmt)
        return int(current or 0) + 1
