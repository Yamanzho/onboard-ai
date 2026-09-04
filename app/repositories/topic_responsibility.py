from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.topic_responsibility import TopicResponsibility
from app.repositories.base import BaseRepository


class TopicResponsibilityRepository(BaseRepository[TopicResponsibility]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TopicResponsibility)

    async def get_by_topic_id(self, topic_id: UUID) -> TopicResponsibility | None:
        self._ensure_rls_context()
        stmt = (
            select(TopicResponsibility)
            .options(
                selectinload(TopicResponsibility.department),
                selectinload(TopicResponsibility.employee),
                selectinload(TopicResponsibility.topic),
            )
            .where(TopicResponsibility.topic_id == topic_id)
        )
        result = await self._session.scalars(stmt)
        return result.first()
