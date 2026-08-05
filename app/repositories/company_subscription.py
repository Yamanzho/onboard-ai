from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company_subscription import CompanySubscription
from app.repositories.base import BaseRepository


class CompanySubscriptionRepository(BaseRepository[CompanySubscription]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CompanySubscription)

    async def get_current_for_company(self, company_id: UUID) -> CompanySubscription | None:
        stmt = (
            select(CompanySubscription)
            .where(
                CompanySubscription.company_id == company_id,
                CompanySubscription.is_current.is_(True),
            )
            .order_by(CompanySubscription.created_at.desc())
            .limit(1)
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_for_company(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[CompanySubscription]:
        stmt = (
            select(CompanySubscription)
            .where(CompanySubscription.company_id == company_id)
            .order_by(CompanySubscription.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())
