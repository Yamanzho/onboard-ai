from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import AssignmentStatus
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
        Index("ix_assignments_company_id_status", "company_id", "status"),
        Index("ix_assignments_employee_id_status", "employee_id", "status"),
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
    assigned_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
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
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship(back_populates="assignments")
    employee: Mapped[Employee] = relationship(
        back_populates="assignments",
        foreign_keys=[employee_id],
    )
    program: Mapped[OnboardingProgram] = relationship(back_populates="assignments")
    assigned_by: Mapped[Optional[Employee]] = relationship(
        back_populates="assigned_assignments",
        foreign_keys=[assigned_by_id],
    )
    progress_records: Mapped[list[Progress]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Assignment id={self.id} status={self.status!r}>"
