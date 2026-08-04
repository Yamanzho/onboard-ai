from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import StepType
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.onboarding_program import OnboardingProgram
    from app.db.models.progress import Progress


class Step(Base, TimestampMixin):
    __tablename__ = "steps"
    __table_args__ = (
        CheckConstraint(
            "step_type IN ('content', 'task', 'quiz', 'ack')",
            name="ck_steps_step_type",
        ),
        CheckConstraint("position >= 0", name="ck_steps_position_non_negative"),
        UniqueConstraint("program_id", "position", name="uq_steps_program_id_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onboarding_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    step_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=StepType.CONTENT.value,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    program: Mapped[OnboardingProgram] = relationship(back_populates="steps")
    progress_records: Mapped[list[Progress]] = relationship(
        back_populates="step",
    )

    def __repr__(self) -> str:
        return f"<Step id={self.id} position={self.position} title={self.title!r}>"
