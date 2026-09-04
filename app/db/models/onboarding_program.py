from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.assignment import Assignment
    from app.db.models.company import Company
    from app.db.models.step import Step


class OnboardingProgram(Base, TimestampMixin):
    __tablename__ = "onboarding_programs"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_onboarding_programs_revision_positive"),
        Index("ix_onboarding_programs_company_id_is_active", "company_id", "is_active"),
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
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    company: Mapped[Company] = relationship(back_populates="onboarding_programs")
    steps: Mapped[list[Step]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="Step.position",
    )
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="program",
    )

    def __repr__(self) -> str:
        return f"<OnboardingProgram id={self.id} title={self.title!r}>"
