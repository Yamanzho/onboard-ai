from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ai_conversation import AIConversation
from app.repositories.base import BaseRepository


class AIConversationRepository(BaseRepository[AIConversation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AIConversation)
