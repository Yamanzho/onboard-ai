from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge_article_link import KnowledgeArticleLink
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT


class KnowledgeArticleLinkRepository(BaseRepository[KnowledgeArticleLink]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeArticleLink)

    async def list_by_article_id(
        self,
        article_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeArticleLink]:
        self._ensure_rls_context()
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt = (
            select(KnowledgeArticleLink)
            .where(KnowledgeArticleLink.article_id == article_id)
            .order_by(KnowledgeArticleLink.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_by_target(
        self,
        company_id: UUID,
        *,
        target_type: str,
        target_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeArticleLink]:
        self._ensure_rls_context()
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt = (
            select(KnowledgeArticleLink)
            .where(
                KnowledgeArticleLink.company_id == company_id,
                KnowledgeArticleLink.target_type == target_type,
                KnowledgeArticleLink.target_id == target_id,
            )
            .order_by(KnowledgeArticleLink.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def delete_by_article_id(self, article_id: UUID) -> int:
        self._ensure_rls_context()
        stmt = delete(KnowledgeArticleLink).where(
            KnowledgeArticleLink.article_id == article_id,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def delete_by_article_id_and_type(
        self,
        article_id: UUID,
        target_type: str,
    ) -> int:
        self._ensure_rls_context()
        stmt = delete(KnowledgeArticleLink).where(
            KnowledgeArticleLink.article_id == article_id,
            KnowledgeArticleLink.target_type == target_type,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)
