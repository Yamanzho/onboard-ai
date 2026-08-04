from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ProgressStatus
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.assignment import Assignment
    from app.db.models.step import Step


class Progress(Base, TimestampMixin):
    __tablename__ = "progress"
    __table_args__ = (
        CheckConstraint(
            "status IN ('not_started', 'in_progress', 'completed', 'skipped')",
            name="ck_progress_status",
        ),
        UniqueConstraint("assignment_id", "step_id", name="uq_progress_assignment_id_step_id"),
        Index("ix_progress_assignment_id_status", "assignment_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("steps.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProgressStatus.NOT_STARTED.value,
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    assignment: Mapped[Assignment] = relationship(back_populates="progress_records")
    step: Mapped[Step] = relationship(back_populates="progress_records")

    def __repr__(self) -> str:
        return f"<Progress id={self.id} status={self.status!r}>"
