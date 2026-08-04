from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ConversationStatus
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.assignment import Assignment
    from app.db.models.company import Company
    from app.db.models.employee import Employee


class AIConversation(Base, TimestampMixin):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed')",
            name="ck_ai_conversations_status",
        ),
        Index("ix_ai_conversations_company_id_created_at", "company_id", "created_at"),
        Index("ix_ai_conversations_employee_id_status", "employee_id", "status"),
        Index(
            "ix_ai_conversations_assignment_id",
            "assignment_id",
            postgresql_where=text("assignment_id IS NOT NULL"),
        ),
        Index("ix_ai_conversations_telegram_chat_id_status", "telegram_chat_id", "status"),
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
    assignment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConversationStatus.ACTIVE.value,
    )
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship(back_populates="ai_conversations")
    employee: Mapped[Employee] = relationship(back_populates="ai_conversations")
    assignment: Mapped[Optional[Assignment]] = relationship(back_populates="ai_conversations")

    def __repr__(self) -> str:
        return f"<AIConversation id={self.id} status={self.status!r}>"
