from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class TelegramOutboundMessage(Base, TimestampMixin):
    """Tenant-owned durable intent for one Telegram sendMessage operation."""

    __tablename__ = "telegram_outbound_messages"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('ai_chat', 'quiz_result')",
            name="ck_telegram_outbound_source_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed')",
            name="ck_telegram_outbound_status",
        ),
        CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4096",
            name="ck_telegram_outbound_body_length",
        ),
        CheckConstraint(
            "parse_mode IS NULL OR parse_mode = 'HTML'",
            name="ck_telegram_outbound_parse_mode",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_telegram_outbound_attempt_count",
        ),
        UniqueConstraint(
            "source_type",
            "source_key",
            name="uq_telegram_outbound_source",
        ),
        Index(
            "ix_telegram_outbound_due",
            "next_attempt_at",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_telegram_outbound_stale_sending",
            "lease_expires_at",
            postgresql_where=text("status = 'sending'"),
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
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    parse_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    telegram_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    last_error_category: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    owner_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<TelegramOutboundMessage id={self.id} "
            f"source_type={self.source_type!r} status={self.status!r}>"
        )
