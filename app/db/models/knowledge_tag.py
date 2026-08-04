from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.knowledge_article import KnowledgeArticle


class KnowledgeTag(Base, TimestampMixin):
    """Normalized tag vocabulary within a company tenant."""

    __tablename__ = "knowledge_tags"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "slug",
            name="uq_knowledge_tags_company_id_slug",
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
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)

    company: Mapped[Company] = relationship(back_populates="knowledge_tags")
    articles: Mapped[list[KnowledgeArticle]] = relationship(
        secondary="knowledge_article_tags",
        back_populates="tags",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeTag id={self.id} slug={self.slug!r}>"
