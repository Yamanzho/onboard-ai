from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.platform_audit_log import PlatformAuditLog
from app.repositories.base import BaseRepository


class PlatformAuditLogRepository(BaseRepository[PlatformAuditLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PlatformAuditLog)

    async def list_recent(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        company_id: UUID | None = None,
    ) -> list[PlatformAuditLog]:
        self._ensure_rls_context()
        stmt = select(PlatformAuditLog).order_by(PlatformAuditLog.created_at.desc())
        if company_id is not None:
            stmt = stmt.where(PlatformAuditLog.company_id == company_id)
        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.scalars(stmt)
        return list(result.all())
