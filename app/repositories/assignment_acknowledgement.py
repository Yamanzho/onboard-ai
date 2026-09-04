from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.assignment_acknowledgement_item import AssignmentAcknowledgementItem
from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.repositories.base import BaseRepository


class AssignmentAcknowledgementItemRepository(BaseRepository[AssignmentAcknowledgementItem]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AssignmentAcknowledgementItem)

    async def list_by_assignment_id(
        self,
        assignment_id: UUID,
    ) -> list[AssignmentAcknowledgementItem]:
        self._ensure_rls_context()
        stmt = (
            select(AssignmentAcknowledgementItem)
            .where(AssignmentAcknowledgementItem.assignment_id == assignment_id)
            .options(selectinload(AssignmentAcknowledgementItem.article_version))
            .order_by(AssignmentAcknowledgementItem.position.asc())
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_by_assignment_ids(
        self,
        assignment_ids: Sequence[UUID],
    ) -> list[AssignmentAcknowledgementItem]:
        self._ensure_rls_context()
        if not assignment_ids:
            return []
        stmt = (
            select(AssignmentAcknowledgementItem)
            .where(AssignmentAcknowledgementItem.assignment_id.in_(list(assignment_ids)))
            .options(selectinload(AssignmentAcknowledgementItem.article_version))
            .order_by(
                AssignmentAcknowledgementItem.assignment_id.asc(),
                AssignmentAcknowledgementItem.position.asc(),
            )
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_by_id_with_version(
        self,
        item_id: UUID,
    ) -> AssignmentAcknowledgementItem | None:
        self._ensure_rls_context()
        stmt = (
            select(AssignmentAcknowledgementItem)
            .where(AssignmentAcknowledgementItem.id == item_id)
            .options(selectinload(AssignmentAcknowledgementItem.article_version))
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def get_version(self, version_id: UUID) -> KnowledgeArticleVersion | None:
        self._ensure_rls_context()
        return await self._session.get(KnowledgeArticleVersion, version_id)
