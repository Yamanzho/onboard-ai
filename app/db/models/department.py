from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.company import Company
    from app.db.models.employee import Employee
    from app.db.models.topic_responsibility import TopicResponsibility


class Department(Base, TimestampMixin):
    """Tenant-scoped organizational unit. Flat in Phase 9B (no parent)."""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "slug",
            name="uq_departments_company_id_slug",
        ),
        Index("ix_departments_company_id_is_active", "company_id", "is_active"),
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
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    company: Mapped[Company] = relationship(back_populates="departments")
    employees: Mapped[list[Employee]] = relationship(
        back_populates="department",
        foreign_keys="Employee.department_id",
    )
    topic_responsibilities: Mapped[list[TopicResponsibility]] = relationship(
        back_populates="department",
    )

    def __repr__(self) -> str:
        return f"<Department id={self.id} slug={self.slug!r}>"
