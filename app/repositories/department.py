from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.department import Department
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository


class DepartmentRepository(BaseRepository[Department]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Department)

    async def get_by_slug(self, company_id: UUID, slug: str) -> Department | None:
        self._ensure_rls_context()
        stmt = select(Department).where(
            Department.company_id == company_id,
            Department.slug == slug,
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Department]:
        self._ensure_rls_context()
        stmt = self._company_list_statement(
            company_id,
            is_active=is_active,
            offset=offset,
            limit=limit,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_by_ids(self, department_ids: list[UUID]) -> list[Department]:
        self._ensure_rls_context()
        if not department_ids:
            return []
        stmt = select(Department).where(Department.id.in_(department_ids))
        result = await self._session.scalars(stmt)
        return list(result.all())

    def _company_list_statement(
        self,
        company_id: UUID,
        *,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> Select[tuple[Department]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[Department]] = select(Department).where(
            Department.company_id == company_id,
        )
        if is_active is not None:
            stmt = stmt.where(Department.is_active.is_(is_active))
        return stmt.order_by(Department.name.asc()).offset(offset).limit(limit)
