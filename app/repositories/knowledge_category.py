from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge_category import KnowledgeCategory
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT


class KnowledgeCategoryRepository(BaseRepository[KnowledgeCategory]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeCategory)

    async def get_by_slug(self, company_id: UUID, slug: str) -> KnowledgeCategory | None:
        self._ensure_rls_context()
        stmt = select(KnowledgeCategory).where(
            KnowledgeCategory.company_id == company_id,
            KnowledgeCategory.slug == slug,
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        parent_id: UUID | None = None,
        roots_only: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeCategory]:
        self._ensure_rls_context()
        stmt = self._company_list_statement(
            company_id,
            parent_id=parent_id,
            roots_only=roots_only,
            offset=offset,
            limit=limit,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_children(
        self,
        company_id: UUID,
        parent_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeCategory]:
        return await self.list_by_company_id(
            company_id,
            parent_id=parent_id,
            offset=offset,
            limit=limit,
        )

    def _company_list_statement(
        self,
        company_id: UUID,
        *,
        parent_id: UUID | None,
        roots_only: bool,
        offset: int,
        limit: int,
    ) -> Select[tuple[KnowledgeCategory]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[KnowledgeCategory]] = select(KnowledgeCategory).where(
            KnowledgeCategory.company_id == company_id,
        )
        if roots_only:
            stmt = stmt.where(KnowledgeCategory.parent_id.is_(None))
        elif parent_id is not None:
            stmt = stmt.where(KnowledgeCategory.parent_id == parent_id)

        return (
            stmt.order_by(KnowledgeCategory.position.asc(), KnowledgeCategory.name.asc())
            .offset(offset)
            .limit(limit)
        )
