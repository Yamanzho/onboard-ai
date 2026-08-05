from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.ai_conversation import AIConversation
    from app.db.models.assignment import Assignment
    from app.db.models.company_subscription import CompanySubscription
    from app.db.models.employee import Employee
    from app.db.models.knowledge_article import KnowledgeArticle
    from app.db.models.knowledge_article_link import KnowledgeArticleLink
    from app.db.models.knowledge_category import KnowledgeCategory
    from app.db.models.knowledge_tag import KnowledgeTag
    from app.db.models.onboarding_program import OnboardingProgram
    from app.db.models.subscription_history import SubscriptionHistoryEvent


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)

    employees: Mapped[list[Employee]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    onboarding_programs: Mapped[list[OnboardingProgram]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    knowledge_categories: Mapped[list[KnowledgeCategory]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    knowledge_tags: Mapped[list[KnowledgeTag]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    knowledge_articles: Mapped[list[KnowledgeArticle]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    knowledge_article_links: Mapped[list[KnowledgeArticleLink]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    ai_conversations: Mapped[list[AIConversation]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    subscriptions: Mapped[list[CompanySubscription]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    subscription_history: Mapped[list[SubscriptionHistoryEvent]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Company id={self.id} slug={self.slug!r}>"
