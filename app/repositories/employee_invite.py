from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import InvitePurpose
from app.db.models.employee_invite import EmployeeInvite
from app.repositories.base import BaseRepository

_ONBOARDING_PURPOSES = (
    InvitePurpose.EMPLOYEE.value,
    InvitePurpose.HR.value,
    InvitePurpose.ADMIN.value,
)


@dataclass(frozen=True, slots=True)
class EmployeeInviteHistoryRow:
    """Safe invite metadata for admin history — never includes token_hash."""

    id: UUID
    purpose: str
    invited_email: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None


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

    async def list_by_employee_id(
        self,
        employee_id: UUID,
        company_id: UUID,
    ) -> list[EmployeeInviteHistoryRow]:
        """Onboarding invite history for one employee in one company.

        Selects metadata columns only (never ``token_hash``). Excludes
        ``password_reset``. Caller must already have verified tenant access
        and entered a mode that can read invite rows (platform RLS).
        """
        self._ensure_rls_context()
        stmt = (
            select(
                EmployeeInvite.id,
                EmployeeInvite.purpose,
                EmployeeInvite.invited_email,
                EmployeeInvite.created_at,
                EmployeeInvite.expires_at,
                EmployeeInvite.used_at,
            )
            .where(
                EmployeeInvite.employee_id == employee_id,
                EmployeeInvite.company_id == company_id,
                EmployeeInvite.purpose.in_(_ONBOARDING_PURPOSES),
            )
            .order_by(EmployeeInvite.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [
            EmployeeInviteHistoryRow(
                id=row.id,
                purpose=row.purpose,
                invited_email=row.invited_email,
                created_at=row.created_at,
                expires_at=row.expires_at,
                used_at=row.used_at,
            )
            for row in result.all()
        ]

    async def invalidate_unused_for_employee(
        self,
        employee_id: UUID,
        *,
        purpose: str | None = None,
    ) -> int:
        """Mark unused invites for an employee as used (resend / accept / reset).

        When ``purpose`` is set, only invites with that purpose are invalidated.
        """
        self._ensure_rls_context()
        conditions = [
            EmployeeInvite.employee_id == employee_id,
            EmployeeInvite.used_at.is_(None),
        ]
        if purpose is not None:
            conditions.append(EmployeeInvite.purpose == purpose)
        stmt = (
            update(EmployeeInvite)
            .where(*conditions)
            .values(used_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
