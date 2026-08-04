from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeArticleTag(Base):
    """Association between knowledge articles and normalized tags."""

    __tablename__ = "knowledge_article_tags"
    __table_args__ = (
        PrimaryKeyConstraint(
            "article_id",
            "tag_id",
            name="pk_knowledge_article_tags",
        ),
    )

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeArticleTag article_id={self.article_id} tag_id={self.tag_id}>"
        )
