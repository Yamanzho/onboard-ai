from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import PaymentStatus, SubscriptionStatus, SubscriptionTier
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.subscription_history import SubscriptionHistoryEvent


class CompanySubscription(Base, TimestampMixin):
    __tablename__ = "company_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "tier IN ('starter', 'professional', 'enterprise')",
            name="ck_company_subscriptions_tier",
        ),
        CheckConstraint(
            "status IN ('trial', 'active', 'suspended', 'expired', 'blocked')",
            name="ck_company_subscriptions_status",
        ),
        CheckConstraint(
            "payment_status IN ('unpaid', 'paid', 'past_due')",
            name="ck_company_subscriptions_payment_status",
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
    tier: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SubscriptionTier.STARTER.value,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SubscriptionStatus.TRIAL.value,
    )
    payment_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PaymentStatus.UNPAID.value,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    employee_limit: Mapped[int] = mapped_column(nullable=False, default=10)
    program_limit: Mapped[int] = mapped_column(nullable=False, default=3)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    company: Mapped[Company] = relationship(back_populates="subscriptions")
    history_events: Mapped[list[SubscriptionHistoryEvent]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
    )
