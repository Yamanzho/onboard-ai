from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import AssignmentType
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.assignment import Assignment
    from app.db.models.knowledge_article import KnowledgeArticle
    from app.db.models.knowledge_article_version import KnowledgeArticleVersion


class AssignmentAcknowledgementItem(Base, TimestampMixin):
    """Exact KnowledgeArticleVersion bound to an acknowledgement assignment."""

    __tablename__ = "assignment_acknowledgement_items"
    __table_args__ = (
        CheckConstraint(
            "assignment_type = 'acknowledgement'",
            name="ck_ack_items_assignment_type",
        ),
        CheckConstraint("position >= 1", name="ck_ack_items_position_positive"),
        UniqueConstraint(
            "assignment_id",
            "position",
            name="uq_ack_items_assignment_id_position",
        ),
        UniqueConstraint(
            "assignment_id",
            "article_id",
            name="uq_ack_items_assignment_id_article_id",
        ),
        UniqueConstraint(
            "assignment_id",
            "article_version_id",
            name="uq_ack_items_assignment_id_article_version_id",
        ),
        ForeignKeyConstraint(
            ["assignment_id", "assignment_type"],
            ["assignments.id", "assignments.assignment_type"],
            name="fk_ack_items_assignment_id_type",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["article_id", "article_version_id"],
            ["knowledge_article_versions.article_id", "knowledge_article_versions.id"],
            name="fk_ack_items_article_version_belongs",
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
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    assignment_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AssignmentType.ACKNOWLEDGEMENT.value,
        server_default=text("'acknowledgement'"),
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_articles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    article_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_article_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    assignment: Mapped[Assignment] = relationship(
        back_populates="acknowledgement_items",
        foreign_keys=[assignment_id],
    )
    article: Mapped[KnowledgeArticle] = relationship(foreign_keys=[article_id])
    article_version: Mapped[KnowledgeArticleVersion] = relationship(
        foreign_keys=[article_version_id],
    )

    def __repr__(self) -> str:
        return (
            f"<AssignmentAcknowledgementItem id={self.id} "
            f"assignment_id={self.assignment_id} position={self.position}>"
        )
