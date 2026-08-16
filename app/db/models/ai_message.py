from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ai_constants import MAX_CONVERSATION_MESSAGE_CHARS
from app.db.base import Base
from app.db.enums import AIMessageRole
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.ai_conversation import AIConversation
    from app.db.models.company import Company


class AIMessage(Base, TimestampMixin):
    """One user or assistant turn. Content is DATA, never ACL or log payload."""

    __tablename__ = "ai_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_ai_messages_role",
        ),
        CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_ai_messages_content_not_blank",
        ),
        CheckConstraint(
            f"char_length(content) <= {MAX_CONVERSATION_MESSAGE_CHARS}",
            name="ck_ai_messages_content_max_length",
        ),
        Index(
            "ix_ai_messages_conversation_id_created_at",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AIMessageRole.USER.value,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    no_answer: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")
    company: Mapped[Company] = relationship()

    def __repr__(self) -> str:
        return f"<AIMessage id={self.id} role={self.role!r}>"
