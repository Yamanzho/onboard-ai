from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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
from app.db.enums import KnowledgeBodyFormat, KnowledgeIndexStatus
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
        CheckConstraint(
            "index_status IN ('pending', 'indexing', 'indexed', 'failed')",
            name="ck_knowledge_article_versions_index_status",
        ),
        CheckConstraint(
            "embedding_dimension IS NULL OR embedding_dimension > 0",
            name="ck_knowledge_article_versions_embedding_dimension_positive",
        ),
        CheckConstraint(
            "indexed_chunk_count IS NULL OR indexed_chunk_count > 0",
            name="ck_knowledge_article_versions_indexed_chunk_count_positive",
        ),
        CheckConstraint(
            "(indexing_owner_token IS NULL) = (indexing_lease_expires_at IS NULL)",
            name="ck_knowledge_article_versions_indexing_lease_pair",
        ),
        CheckConstraint(
            "index_status <> 'indexed' OR "
            "(embedding_provider IS NOT NULL AND embedding_model IS NOT NULL "
            "AND embedding_dimension IS NOT NULL AND indexed_chunk_count IS NOT NULL "
            "AND indexed_at IS NOT NULL)",
            name="ck_knowledge_article_versions_indexed_metadata",
        ),
        Index("ix_knowledge_article_versions_article_id_version", "article_id", "version"),
        Index(
            "ix_knowledge_article_versions_company_id_index_status",
            "company_id",
            "index_status",
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
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    index_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=KnowledgeIndexStatus.PENDING.value,
    )
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexed_chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    indexing_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexing_owner_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    indexing_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    article: Mapped[KnowledgeArticle] = relationship(
        back_populates="versions",
        foreign_keys=[article_id],
    )
    created_by: Mapped[Employee | None] = relationship(
        back_populates="knowledge_article_versions",
    )

    @property
    def indexing_in_progress(self) -> bool:
        lease = self.indexing_lease_expires_at
        if self.indexing_owner_token is None or lease is None:
            return False
        return lease > datetime.now(UTC)

    @property
    def index_stale(self) -> bool:
        return bool(
            self.index_status == KnowledgeIndexStatus.INDEXED.value
            and self.indexing_failed_at is not None
            and self.indexed_at is not None
            and self.indexing_failed_at > self.indexed_at
        )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeArticleVersion id={self.id} "
            f"article_id={self.article_id} version={self.version}>"
        )
