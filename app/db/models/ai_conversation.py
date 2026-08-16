from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ConversationStatus
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.ai_message import AIMessage
    from app.db.models.company import Company
    from app.db.models.employee import Employee


class AIConversation(Base, TimestampMixin):
    """Employee-owned AI chat thread. Storage only — not KB authorization."""

    __tablename__ = "ai_conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_ai_conversations_status",
        ),
        Index(
            "ix_ai_conversations_company_id_employee_id_updated_at",
            "company_id",
            "employee_id",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConversationStatus.ACTIVE.value,
    )

    company: Mapped[Company] = relationship(back_populates="ai_conversations")
    employee: Mapped[Employee] = relationship(back_populates="ai_conversations")
    messages: Mapped[list[AIMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AIConversation id={self.id} status={self.status!r}>"
