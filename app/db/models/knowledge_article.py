from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import KnowledgeArticleStatus, KnowledgeVisibility
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.employee import Employee
    from app.db.models.knowledge_article_link import KnowledgeArticleLink
    from app.db.models.knowledge_article_version import KnowledgeArticleVersion
    from app.db.models.knowledge_category import KnowledgeCategory
    from app.db.models.knowledge_tag import KnowledgeTag


class KnowledgeArticle(Base, TimestampMixin):
    """Knowledge article identity (content lives on versions)."""

    __tablename__ = "knowledge_articles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_knowledge_articles_status",
        ),
        CheckConstraint(
            "visibility IN ('company', 'program')",
            name="ck_knowledge_articles_visibility",
        ),
        Index("ix_knowledge_articles_company_id_status", "company_id", "status"),
        Index(
            "ix_knowledge_articles_category_id",
            "category_id",
            postgresql_where=text("category_id IS NOT NULL"),
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
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge_article_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_knowledge_articles_current_version_id",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=KnowledgeArticleStatus.DRAFT.value,
    )
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=KnowledgeVisibility.COMPANY.value,
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    company: Mapped[Company] = relationship(back_populates="knowledge_articles")
    category: Mapped[Optional[KnowledgeCategory]] = relationship(
        back_populates="articles",
    )
    created_by: Mapped[Optional[Employee]] = relationship(
        back_populates="knowledge_articles",
    )
    current_version: Mapped[Optional[KnowledgeArticleVersion]] = relationship(
        foreign_keys=[current_version_id],
        post_update=True,
    )
    versions: Mapped[list[KnowledgeArticleVersion]] = relationship(
        back_populates="article",
        foreign_keys="KnowledgeArticleVersion.article_id",
        cascade="all, delete-orphan",
        order_by="KnowledgeArticleVersion.version",
    )
    tags: Mapped[list[KnowledgeTag]] = relationship(
        secondary="knowledge_article_tags",
        back_populates="articles",
    )
    links: Mapped[list[KnowledgeArticleLink]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeArticle id={self.id} status={self.status!r}>"
