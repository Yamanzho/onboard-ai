from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import KnowledgeBodyFormat
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.employee import Employee
    from app.db.models.knowledge_article import KnowledgeArticle


class KnowledgeArticleVersion(Base, TimestampMixin):
    """Immutable content snapshot for a knowledge article."""

    __tablename__ = "knowledge_article_versions"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "version",
            name="uq_knowledge_article_versions_article_id_version",
        ),
        CheckConstraint("version >= 1", name="ck_knowledge_article_versions_version_positive"),
        CheckConstraint(
            "body_format IN ('markdown', 'html', 'plain')",
            name="ck_knowledge_article_versions_body_format",
        ),
        Index("ix_knowledge_article_versions_article_id_version", "article_id", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_format: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=KnowledgeBodyFormat.MARKDOWN.value,
    )
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    article: Mapped[KnowledgeArticle] = relationship(
        back_populates="versions",
        foreign_keys=[article_id],
    )
    created_by: Mapped[Optional[Employee]] = relationship(
        back_populates="knowledge_article_versions",
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeArticleVersion id={self.id} "
            f"article_id={self.article_id} version={self.version}>"
        )
