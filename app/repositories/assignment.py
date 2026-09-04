from uuid import UUID

from sqlalchemy import Select, case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AssignmentStatus
from app.db.models.assignment import Assignment
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository

_ACTIVE_STATUSES = (
    AssignmentStatus.PENDING.value,
    AssignmentStatus.IN_PROGRESS.value,
)
_HISTORY_STATUSES = {
    AssignmentStatus.COMPLETED.value,
    AssignmentStatus.CANCELLED.value,
}

_PRIORITY_RANK = case(
    (Assignment.priority == "critical", 0),
    (Assignment.priority == "important", 1),
    else_=2,
)
_DUE_MISSING = case((Assignment.due_at.is_(None), 1), else_=0)
_STATUS_RANK = case(
    (Assignment.status == AssignmentStatus.IN_PROGRESS.value, 0),
    (Assignment.status == AssignmentStatus.PENDING.value, 1),
    else_=2,
)


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

    async def list_active_by_program_and_employees(
        self,
        program_id: UUID,
        employee_ids: list[UUID],
    ) -> list[Assignment]:
        """Active (pending/in_progress) rows for a program and employee set."""
        self._ensure_rls_context()
        if not employee_ids:
            return []
        stmt = select(Assignment).where(
            Assignment.program_id == program_id,
            Assignment.employee_id.in_(employee_ids),
            Assignment.status.in_(_ACTIVE_STATUSES),
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
        return stmt.order_by(*self._order_by(status)).offset(offset).limit(limit)

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
        return stmt.order_by(*self._order_by(status)).offset(offset).limit(limit)

    def _order_by(self, status: str | None):
        if status in _HISTORY_STATUSES:
            return (
                Assignment.completed_at.desc().nulls_last(),
                Assignment.assigned_at.desc(),
            )
        return (
            _PRIORITY_RANK.asc(),
            _DUE_MISSING.asc(),
            Assignment.due_at.asc().nulls_last(),
            _STATUS_RANK.asc(),
            Assignment.assigned_at.desc(),
        )
