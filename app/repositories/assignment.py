from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assignment import Assignment
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository


class AssignmentRepository(BaseRepository[Assignment]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Assignment)

    async def list_by_employee_id(
        self,
        employee_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Assignment]:
        self._ensure_rls_context()
        stmt = self._employee_list_statement(
            employee_id,
            offset=offset,
            limit=limit,
            status=status,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
        employee_id: UUID | None = None,
    ) -> list[Assignment]:
        self._ensure_rls_context()
        stmt = self._company_list_statement(
            company_id,
            offset=offset,
            limit=limit,
            status=status,
            employee_id=employee_id,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    def _employee_list_statement(
        self,
        employee_id: UUID,
        *,
        offset: int,
        limit: int,
        status: str | None,
    ) -> Select[tuple[Assignment]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[Assignment]] = select(Assignment).where(
            Assignment.employee_id == employee_id,
        )
        if status is not None:
            stmt = stmt.where(Assignment.status == status)
        return stmt.order_by(Assignment.assigned_at.desc()).offset(offset).limit(limit)

    def _company_list_statement(
        self,
        company_id: UUID,
        *,
        offset: int,
        limit: int,
        status: str | None,
        employee_id: UUID | None,
    ) -> Select[tuple[Assignment]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[Assignment]] = select(Assignment).where(
            Assignment.company_id == company_id,
        )
        if status is not None:
            stmt = stmt.where(Assignment.status == status)
        if employee_id is not None:
            stmt = stmt.where(Assignment.employee_id == employee_id)
        return stmt.order_by(Assignment.assigned_at.desc()).offset(offset).limit(limit)
