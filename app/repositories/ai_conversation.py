from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ConversationStatus
from app.db.models.ai_conversation import AIConversation
from app.db.models.ai_message import AIMessage
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository


@dataclass(frozen=True, slots=True)
class ConversationSummaryRow:
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None
    message_count: int


class AIConversationRepository(BaseRepository[AIConversation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AIConversation)

    async def get_owned(
        self,
        *,
        conversation_id: UUID,
        company_id: UUID,
        employee_id: UUID,
    ) -> AIConversation | None:
        """Load only when id, tenant, and employee owner all match."""
        self._ensure_rls_context()
        stmt = select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.company_id == company_id,
            AIConversation.employee_id == employee_id,
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_owned(
        self,
        *,
        company_id: UUID,
        employee_id: UUID,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[AIConversation]:
        self._ensure_rls_context()
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
        conditions = [
            AIConversation.company_id == company_id,
            AIConversation.employee_id == employee_id,
        ]
        if status is not None:
            conditions.append(AIConversation.status == status)
        stmt = (
            select(AIConversation)
            .where(*conditions)
            .order_by(
                AIConversation.updated_at.desc(),
                AIConversation.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_owned_summaries(
        self,
        *,
        company_id: UUID,
        employee_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ConversationSummaryRow]:
        """Active threads with last-message preview. One query, no N+1."""
        self._ensure_rls_context()
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
        last_preview = (
            select(AIMessage.content)
            .where(
                AIMessage.conversation_id == AIConversation.id,
                AIMessage.company_id == company_id,
            )
            .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
            .limit(1)
            .correlate(AIConversation)
            .scalar_subquery()
        )
        msg_count = (
            select(func.count())
            .select_from(AIMessage)
            .where(
                AIMessage.conversation_id == AIConversation.id,
                AIMessage.company_id == company_id,
            )
            .correlate(AIConversation)
            .scalar_subquery()
        )
        stmt = (
            select(
                AIConversation.id,
                AIConversation.title,
                AIConversation.created_at,
                AIConversation.updated_at,
                last_preview,
                msg_count,
            )
            .where(
                AIConversation.company_id == company_id,
                AIConversation.employee_id == employee_id,
                AIConversation.status == ConversationStatus.ACTIVE.value,
            )
            .order_by(
                AIConversation.updated_at.desc(),
                AIConversation.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        rows = await self._session.execute(stmt)
        return [
            ConversationSummaryRow(
                id=row[0],
                title=row[1],
                created_at=row[2],
                updated_at=row[3],
                last_message_preview=row[4],
                message_count=int(row[5] or 0),
            )
            for row in rows.all()
        ]

