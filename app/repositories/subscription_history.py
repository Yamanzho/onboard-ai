from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.subscription_history import SubscriptionHistoryEvent
from app.repositories.base import BaseRepository


class SubscriptionHistoryRepository(BaseRepository[SubscriptionHistoryEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SubscriptionHistoryEvent)

    async def list_for_company(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SubscriptionHistoryEvent]:
        stmt = (
            select(SubscriptionHistoryEvent)
            .where(SubscriptionHistoryEvent.company_id == company_id)
            .order_by(SubscriptionHistoryEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())
