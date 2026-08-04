from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.knowledge_article import KnowledgeArticle


class KnowledgeCategory(Base, TimestampMixin):
    """Tenant-scoped taxonomy node for knowledge articles."""

    __tablename__ = "knowledge_categories"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "slug",
            name="uq_knowledge_categories_company_id_slug",
        ),
        CheckConstraint("position >= 0", name="ck_knowledge_categories_position_non_negative"),
        Index("ix_knowledge_categories_company_id_parent_id", "company_id", "parent_id"),
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
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    company: Mapped[Company] = relationship(back_populates="knowledge_categories")
    parent: Mapped[Optional[KnowledgeCategory]] = relationship(
        back_populates="children",
        remote_side="KnowledgeCategory.id",
    )
    children: Mapped[list[KnowledgeCategory]] = relationship(
        back_populates="parent",
    )
    articles: Mapped[list[KnowledgeArticle]] = relationship(
        back_populates="category",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeCategory id={self.id} slug={self.slug!r}>"
