from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company_audit_log import CompanyAuditLog
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository


class CompanyAuditLogRepository(BaseRepository[CompanyAuditLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CompanyAuditLog)

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[CompanyAuditLog]:
        self._ensure_rls_context()
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt = select(CompanyAuditLog).where(CompanyAuditLog.company_id == company_id)
        if action is not None:
            stmt = stmt.where(CompanyAuditLog.action == action)
        if resource_type is not None:
            stmt = stmt.where(CompanyAuditLog.resource_type == resource_type)
        stmt = (
            stmt.order_by(CompanyAuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())
