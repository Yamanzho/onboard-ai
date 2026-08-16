from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION
from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.knowledge_article import KnowledgeArticle
    from app.db.models.knowledge_article_version import KnowledgeArticleVersion


class KnowledgeArticleChunk(Base, TimestampMixin):
    """Embedded slice of a published knowledge article version.

    Metadata is a retrieval hint only. ACL authority remains ArticleService
    plus tenant RLS — never this row.
    """

    __tablename__ = "knowledge_article_chunks"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "chunk_index",
            name="uq_knowledge_article_chunks_version_id_chunk_index",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_article_chunks_chunk_index_non_negative",
        ),
        CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_knowledge_article_chunks_content_not_blank",
        ),
        Index(
            "ix_knowledge_article_chunks_company_id_article_id",
            "company_id",
            "article_id",
        ),
        Index(
            "ix_knowledge_article_chunks_company_id_version_id",
            "company_id",
            "version_id",
        ),
        Index(
            "ix_knowledge_article_chunks_article_id",
            "article_id",
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
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_article_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(KB_CHUNK_VECTOR_DIMENSION),
        nullable=False,
    )
    extra: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    company: Mapped[Company] = relationship()
    article: Mapped[KnowledgeArticle] = relationship()
    version: Mapped[KnowledgeArticleVersion] = relationship()

    def __repr__(self) -> str:
        return (
            f"<KnowledgeArticleChunk id={self.id} "
            f"article_id={self.article_id} chunk_index={self.chunk_index}>"
        )
