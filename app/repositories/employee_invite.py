from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.employee_invite import EmployeeInvite
from app.repositories.base import BaseRepository


class EmployeeInviteRepository(BaseRepository[EmployeeInvite]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EmployeeInvite)

    async def get_by_token_hash(self, token_hash: str) -> EmployeeInvite | None:
        stmt = select(EmployeeInvite).where(EmployeeInvite.token_hash == token_hash)
        result = await self._session.scalars(stmt)
        return result.first()
