from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.enums import EmployeeStatus
from app.db.models.employee import Employee
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository

_ORG_LOAD = (
    selectinload(Employee.department),
    selectinload(Employee.manager),
)


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

    async def list_by_telegram_user_id(self, telegram_user_id: int) -> list[Employee]:
        """Identity lookup by Telegram id (platform SELECT). No tenant filter."""
        self._ensure_rls_context()
        stmt = select(Employee).where(Employee.telegram_user_id == telegram_user_id)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_by_email(self, email: str) -> Employee | None:
        """Resolve one employee by normalized email (platform / auth login).

        Emails are unique when non-null (``uq_employees_email_lower``).
        """
        self._ensure_rls_context()
        normalized = email.strip().lower()
        if not normalized:
            return None
        stmt = select(Employee).where(func.lower(func.btrim(Employee.email)) == normalized)
        result = await self._session.scalars(stmt)
        return result.first()

    async def count_by_company_id(self, company_id: UUID) -> int:
        self._ensure_rls_context()
        stmt = select(func.count()).select_from(Employee).where(Employee.company_id == company_id)
        result = await self._session.scalar(stmt)
        return int(result or 0)

    async def get_with_org(self, employee_id: UUID) -> Employee | None:
        """Load an employee with department and manager summaries."""
        self._ensure_rls_context()
        stmt = select(Employee).options(*_ORG_LOAD).where(Employee.id == employee_id)
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
        department_id: UUID | None = None,
        with_org: bool = False,
    ) -> list[Employee]:
        self._ensure_rls_context()
        stmt = self._company_list_statement(
            company_id,
            offset=offset,
            limit=limit,
            status=status,
            department_id=department_id,
            with_org=with_org,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_by_ids(self, employee_ids: list[UUID]) -> list[Employee]:
        self._ensure_rls_context()
        if not employee_ids:
            return []
        stmt = select(Employee).where(Employee.id.in_(employee_ids))
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_non_archived_by_department_ids(
        self,
        department_ids: list[UUID],
    ) -> list[Employee]:
        """Snapshot department members eligible for a new assignment."""
        self._ensure_rls_context()
        if not department_ids:
            return []
        stmt = (
            select(Employee)
            .where(
                Employee.department_id.in_(department_ids),
                Employee.status != EmployeeStatus.ARCHIVED.value,
            )
            .order_by(Employee.full_name.asc(), Employee.id.asc())
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
        department_id: UUID | None = None,
        with_org: bool = False,
    ) -> Select[tuple[Employee]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[Employee]] = select(Employee).where(
            Employee.company_id == company_id,
        )
        if with_org:
            stmt = stmt.options(*_ORG_LOAD)
        if status is not None:
            stmt = stmt.where(Employee.status == status)
        if department_id is not None:
            stmt = stmt.where(Employee.department_id == department_id)
        return stmt.order_by(Employee.created_at.desc()).offset(offset).limit(limit)
