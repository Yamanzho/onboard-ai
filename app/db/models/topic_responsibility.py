from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.department import Department
    from app.db.models.employee import Employee
    from app.db.models.question_topic import QuestionTopic


class TopicResponsibility(Base, TimestampMixin):
    """Maps a question topic to a department and/or named employee."""

    __tablename__ = "topic_responsibilities"
    __table_args__ = (
        UniqueConstraint(
            "topic_id",
            name="uq_topic_responsibilities_topic_id",
        ),
        CheckConstraint(
            "department_id IS NOT NULL OR employee_id IS NOT NULL",
            name="ck_topic_responsibilities_target_present",
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
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    company: Mapped[Company] = relationship(back_populates="topic_responsibilities")
    topic: Mapped[QuestionTopic] = relationship(back_populates="responsibility")
    department: Mapped[Optional[Department]] = relationship(
        back_populates="topic_responsibilities",
    )
    employee: Mapped[Optional[Employee]] = relationship(
        back_populates="topic_responsibilities",
        foreign_keys=[employee_id],
    )

    def __repr__(self) -> str:
        return f"<TopicResponsibility id={self.id} topic_id={self.topic_id}>"
