from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.employee import Employee
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT


class EmployeeRepository(BaseRepository[Employee]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Employee)

    async def get_by_telegram_user_id(
        self,
        company_id: UUID,
        telegram_user_id: int,
    ) -> Employee | None:
        self._ensure_rls_context()
        stmt = select(Employee).where(
            Employee.company_id == company_id,
            Employee.telegram_user_id == telegram_user_id,
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def count_by_company_id(self, company_id: UUID) -> int:
        self._ensure_rls_context()
        stmt = select(func.count()).select_from(Employee).where(Employee.company_id == company_id)
        result = await self._session.scalar(stmt)
        return int(result or 0)

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Employee]:
        self._ensure_rls_context()
        stmt = self._company_list_statement(
            company_id,
            offset=offset,
            limit=limit,
            status=status,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    def _company_list_statement(
        self,
        company_id: UUID,
        *,
        offset: int,
        limit: int,
        status: str | None,
    ) -> Select[tuple[Employee]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[Employee]] = select(Employee).where(
            Employee.company_id == company_id,
        )
        if status is not None:
            stmt = stmt.where(Employee.status == status)
        return stmt.order_by(Employee.created_at.desc()).offset(offset).limit(limit)
