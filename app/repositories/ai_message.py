from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ai_conversation import AIConversation
from app.db.models.ai_message import AIMessage
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository


class AIMessageRepository(BaseRepository[AIMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AIMessage)

    async def get_owned(
        self,
        *,
        message_id: UUID,
        company_id: UUID,
        employee_id: UUID,
    ) -> AIMessage | None:
        """Resolve a message only through its owning conversation."""
        self._ensure_rls_context()
        stmt = (
            select(AIMessage)
            .join(AIConversation, AIConversation.id == AIMessage.conversation_id)
            .where(
                AIMessage.id == message_id,
                AIMessage.company_id == company_id,
                AIConversation.company_id == company_id,
                AIConversation.employee_id == employee_id,
            )
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_for_owned_conversation(
        self,
        *,
        conversation_id: UUID,
        company_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> list[AIMessage]:
        self._ensure_rls_context()
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
        stmt = (
            select(AIMessage)
            .where(
                AIMessage.conversation_id == conversation_id,
                AIMessage.company_id == company_id,
            )
            .order_by(AIMessage.created_at.asc(), AIMessage.id.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_recent_for_owned_conversation(
        self,
        *,
        conversation_id: UUID,
        company_id: UUID,
        limit: int,
    ) -> list[AIMessage]:
        """Newest-first window. Caller reverses for chronological LLM context."""
        self._ensure_rls_context()
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
        stmt = (
            select(AIMessage)
            .where(
                AIMessage.conversation_id == conversation_id,
                AIMessage.company_id == company_id,
            )
            .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())
