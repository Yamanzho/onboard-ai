from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.assignment_rules import is_assignment_overdue
from app.db.base import Base
from app.db.enums import AssignmentPriority, AssignmentStatus
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.employee import Employee
    from app.db.models.onboarding_program import OnboardingProgram
    from app.db.models.progress import Progress


class Assignment(Base, TimestampMixin):
    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'cancelled')",
            name="ck_assignments_status",
        ),
        CheckConstraint(
            "priority IN ('normal', 'important', 'critical')",
            name="ck_assignments_priority",
        ),
        CheckConstraint(
            "program_revision >= 1",
            name="ck_assignments_program_revision_positive",
        ),
        Index("ix_assignments_company_id_status", "company_id", "status"),
        Index("ix_assignments_employee_id_status", "employee_id", "status"),
        Index(
            "ix_assignments_company_id_priority_due_at",
            "company_id",
            "priority",
            "due_at",
        ),
        Index(
            "ix_assignments_employee_id_priority_due_at",
            "employee_id",
            "priority",
            "due_at",
        ),
        Index("ix_assignments_source_batch_id", "source_batch_id"),
        Index("ix_assignments_program_id_status", "program_id", "status"),
        Index(
            "uq_assignments_employee_program_active",
            "employee_id",
            "program_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'in_progress')"),
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
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onboarding_programs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AssignmentStatus.PENDING.value,
    )
    priority: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AssignmentPriority.NORMAL.value,
        server_default=text("'normal'"),
    )
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    program_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    structure_snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship(back_populates="assignments")
    employee: Mapped[Employee] = relationship(
        back_populates="assignments",
        foreign_keys=[employee_id],
    )
    program: Mapped[OnboardingProgram] = relationship(back_populates="assignments")
    assigned_by: Mapped[Employee | None] = relationship(
        back_populates="assigned_assignments",
        foreign_keys=[assigned_by_id],
    )
    progress_records: Mapped[list[Progress]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
    )

    @property
    def overdue(self) -> bool:
        return is_assignment_overdue(self.due_at, self.status)

    def __repr__(self) -> str:
        return f"<Assignment id={self.id} status={self.status!r}>"
