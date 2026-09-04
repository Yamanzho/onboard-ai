from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.ai_conversation import AIConversation
    from app.db.models.assignment import Assignment
    from app.db.models.company import Company
    from app.db.models.department import Department
    from app.db.models.employee_invite import EmployeeInvite
    from app.db.models.knowledge_article import KnowledgeArticle
    from app.db.models.knowledge_article_version import KnowledgeArticleVersion
    from app.db.models.topic_responsibility import TopicResponsibility


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            "role IN ('employee', 'hr', 'admin')",
            name="ck_employees_role",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'archived')",
            name="ck_employees_status",
        ),
        Index("ix_employees_company_id_status", "company_id", "status"),
        Index(
            "uq_employees_company_id_telegram_user_id",
            "company_id",
            "telegram_user_id",
            unique=True,
        ),
        # Shared bot: one real Telegram account → at most one active employee.
        Index(
            "uq_employees_active_telegram_user_id",
            "telegram_user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
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
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EmployeeRole.EMPLOYEE.value,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EmployeeStatus.INVITED.value,
    )
    hired_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    company: Mapped[Company] = relationship(back_populates="employees")
    department: Mapped[Optional[Department]] = relationship(
        back_populates="employees",
        foreign_keys=[department_id],
    )
    manager: Mapped[Optional[Employee]] = relationship(
        remote_side="Employee.id",
        foreign_keys=[manager_id],
    )
    topic_responsibilities: Mapped[list[TopicResponsibility]] = relationship(
        back_populates="employee",
        foreign_keys="TopicResponsibility.employee_id",
    )
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="employee",
        foreign_keys="[Assignment.employee_id]",
        cascade="all, delete-orphan",
    )
    assigned_assignments: Mapped[list[Assignment]] = relationship(
        back_populates="assigned_by",
        foreign_keys="[Assignment.assigned_by_id]",
    )
    knowledge_articles: Mapped[list[KnowledgeArticle]] = relationship(
        back_populates="created_by",
    )
    knowledge_article_versions: Mapped[list[KnowledgeArticleVersion]] = relationship(
        back_populates="created_by",
    )
    ai_conversations: Mapped[list[AIConversation]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
    )
    invites: Mapped[list[EmployeeInvite]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Employee id={self.id} telegram_user_id={self.telegram_user_id}>"
