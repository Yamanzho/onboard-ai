from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ReminderMode
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.assignment import Assignment
    from app.db.models.company import Company
    from app.db.models.employee import Employee


class AssignmentReminderPreference(Base, TimestampMixin):
    """Per-assignment reminder preference and scheduling cursor."""

    __tablename__ = "assignment_reminder_preferences"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('default', 'reduced', 'disabled')",
            name="ck_assignment_reminder_mode",
        ),
        UniqueConstraint(
            "assignment_id",
            name="uq_assignment_reminder_assignment_id",
        ),
        Index("ix_assignment_reminder_preferences_company_id", "company_id"),
        Index("ix_assignment_reminder_preferences_employee_id", "employee_id"),
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
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ReminderMode.DEFAULT.value,
    )
    acknowledged_until_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_automated_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_manual_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_by_employee_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    company: Mapped[Company] = relationship()
    assignment: Mapped[Assignment] = relationship()
    employee: Mapped[Employee] = relationship()

    def __repr__(self) -> str:
        return (
            f"<AssignmentReminderPreference id={self.id} "
            f"mode={self.mode!r} assignment_id={self.assignment_id}>"
        )
