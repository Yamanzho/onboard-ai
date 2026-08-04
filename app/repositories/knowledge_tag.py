from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge_tag import KnowledgeTag
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT


class KnowledgeTagRepository(BaseRepository[KnowledgeTag]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeTag)

    async def get_by_slug(self, company_id: UUID, slug: str) -> KnowledgeTag | None:
        stmt = select(KnowledgeTag).where(
            KnowledgeTag.company_id == company_id,
            KnowledgeTag.slug == slug,
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeTag]:
        stmt = self._company_list_statement(company_id, offset=offset, limit=limit)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def search_by_prefix(
        self,
        company_id: UUID,
        prefix: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeTag]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        pattern = f"{prefix.lower()}%"
        stmt = (
            select(KnowledgeTag)
            .where(
                KnowledgeTag.company_id == company_id,
                KnowledgeTag.slug.like(pattern),
            )
            .order_by(KnowledgeTag.name.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    def _company_list_statement(
        self,
        company_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> Select[tuple[KnowledgeTag]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        return (
            select(KnowledgeTag)
            .where(KnowledgeTag.company_id == company_id)
            .order_by(KnowledgeTag.name.asc())
            .offset(offset)
            .limit(limit)
        )
