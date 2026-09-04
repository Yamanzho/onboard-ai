from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.question_topic import QuestionTopic
from app.db.models.topic_responsibility import TopicResponsibility
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT

_RESP_LOAD = (
    selectinload(QuestionTopic.responsibility).selectinload(
        TopicResponsibility.department
    ),
    selectinload(QuestionTopic.responsibility).selectinload(
        TopicResponsibility.employee
    ),
)


class QuestionTopicRepository(BaseRepository[QuestionTopic]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, QuestionTopic)

    async def get_by_id_with_responsibility(
        self,
        topic_id: UUID,
    ) -> QuestionTopic | None:
        self._ensure_rls_context()
        stmt = (
            select(QuestionTopic)
            .options(*_RESP_LOAD)
            .where(QuestionTopic.id == topic_id)
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def get_by_slug(self, company_id: UUID, slug: str) -> QuestionTopic | None:
        self._ensure_rls_context()
        stmt = (
            select(QuestionTopic)
            .options(*_RESP_LOAD)
            .where(
                QuestionTopic.company_id == company_id,
                QuestionTopic.slug == slug,
            )
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[QuestionTopic]:
        self._ensure_rls_context()
        stmt = self._company_list_statement(
            company_id,
            is_active=is_active,
            offset=offset,
            limit=limit,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    def _company_list_statement(
        self,
        company_id: UUID,
        *,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> Select[tuple[QuestionTopic]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[QuestionTopic]] = (
            select(QuestionTopic)
            .options(*_RESP_LOAD)
            .where(QuestionTopic.company_id == company_id)
        )
        if is_active is not None:
            stmt = stmt.where(QuestionTopic.is_active.is_(is_active))
        return stmt.order_by(QuestionTopic.name.asc()).offset(offset).limit(limit)
