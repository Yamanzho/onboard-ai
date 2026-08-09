from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.employee_invite import EmployeeInvite
from app.repositories.base import BaseRepository


class EmployeeInviteRepository(BaseRepository[EmployeeInvite]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EmployeeInvite)

    async def get_by_token_hash(self, token_hash: str) -> EmployeeInvite | None:
        self._ensure_rls_context()
        stmt = select(EmployeeInvite).where(EmployeeInvite.token_hash == token_hash)
        result = await self._session.scalars(stmt)
        return result.first()

    async def get_by_token_hash_for_update(self, token_hash: str) -> EmployeeInvite | None:
        """Load invite with a row lock to prevent concurrent accept races."""
        self._ensure_rls_context()
        stmt = (
            select(EmployeeInvite)
            .where(EmployeeInvite.token_hash == token_hash)
            .with_for_update()
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def invalidate_unused_for_employee(self, employee_id: UUID) -> int:
        """Mark all unused invites for an employee as used (resend / accept)."""
        self._ensure_rls_context()
        stmt = (
            update(EmployeeInvite)
            .where(
                EmployeeInvite.employee_id == employee_id,
                EmployeeInvite.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
