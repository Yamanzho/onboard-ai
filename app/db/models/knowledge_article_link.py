from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import KnowledgeLinkTargetType
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.knowledge_article import KnowledgeArticle


class KnowledgeArticleLink(Base, TimestampMixin):
    """M:N link from a knowledge article to a program or step."""

    __tablename__ = "knowledge_article_links"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "target_type",
            "target_id",
            name="uq_knowledge_article_links_article_target",
        ),
        CheckConstraint(
            "target_type IN ('program', 'step')",
            name="ck_knowledge_article_links_target_type",
        ),
        Index(
            "ix_knowledge_article_links_company_id_target",
            "company_id",
            "target_type",
            "target_id",
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
    target_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=KnowledgeLinkTargetType.PROGRAM.value,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    company: Mapped[Company] = relationship(back_populates="knowledge_article_links")
    article: Mapped[KnowledgeArticle] = relationship(back_populates="links")

    def __repr__(self) -> str:
        return (
            f"<KnowledgeArticleLink id={self.id} "
            f"target_type={self.target_type!r} target_id={self.target_id}>"
        )
