from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class IdempotencyReceipt(Base, TimestampMixin):
    """Durable claim/result for one explicitly scoped application operation."""

    __tablename__ = "idempotency_receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_idempotency_receipts_status",
        ),
        CheckConstraint(
            "(company_id IS NULL) = (employee_id IS NULL)",
            name="ck_idempotency_receipts_identity_pair",
        ),
        UniqueConstraint(
            "scope",
            "operation",
            "idempotency_key",
            name="uq_idempotency_receipts_scope_operation_key",
        ),
        Index(
            "ix_idempotency_receipts_stale_processing",
            "lease_expires_at",
            postgresql_where=text("status = 'processing'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="processing",
    )
    owner_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=True,
    )
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<IdempotencyReceipt id={self.id} operation={self.operation!r} "
            f"status={self.status!r}>"
        )
