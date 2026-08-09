from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.super_admin import SuperAdmin
from app.repositories.base import BaseRepository


class SuperAdminRepository(BaseRepository[SuperAdmin]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SuperAdmin)

    async def get_by_email(self, email: str) -> SuperAdmin | None:
        self._ensure_rls_context()
        stmt = select(SuperAdmin).where(SuperAdmin.email == email.lower())
        result = await self._session.scalars(stmt)
        return result.first()
