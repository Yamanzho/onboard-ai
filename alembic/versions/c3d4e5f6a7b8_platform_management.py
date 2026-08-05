"""platform management and subscription foundation

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-05 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("companies", sa.Column("logo_url", sa.String(length=2048), nullable=True))
    op.add_column("companies", sa.Column("contact_email", sa.String(length=320), nullable=True))
    op.add_column("companies", sa.Column("contact_phone", sa.String(length=64), nullable=True))
    op.add_column("companies", sa.Column("contact_person", sa.String(length=255), nullable=True))

    op.add_column("employees", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "employees",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "company_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=False, server_default="starter"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="trial"),
        sa.Column(
            "payment_status",
            sa.String(length=32),
            nullable=False,
            server_default="unpaid",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("employee_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("program_limit", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tier IN ('starter', 'professional', 'enterprise')",
            name="ck_company_subscriptions_tier",
        ),
        sa.CheckConstraint(
            "status IN ('trial', 'active', 'suspended', 'expired', 'blocked')",
            name="ck_company_subscriptions_status",
        ),
        sa.CheckConstraint(
            "payment_status IN ('unpaid', 'paid', 'past_due')",
            name="ck_company_subscriptions_payment_status",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_subscriptions_company_id",
        "company_subscriptions",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_company_subscriptions_company_id_is_current",
        "company_subscriptions",
        ["company_id", "is_current"],
        unique=False,
    )

    op.create_table(
        "subscription_history_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=True),
        sa.Column("previous_tier", sa.String(length=32), nullable=True),
        sa.Column("new_tier", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_super_admin_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'status_changed', 'tier_changed', "
            "'renewed', 'auto_renew_changed')",
            name="ck_subscription_history_event_type",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["company_subscriptions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_super_admin_id"],
            ["super_admins.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_subscription_history_events_company_id",
        "subscription_history_events",
        ["company_id"],
        unique=False,
    )

    op.create_table(
        "employee_invites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_email", sa.String(length=320), nullable=False),
        sa.Column("created_by_super_admin_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_super_admin_id"],
            ["super_admins.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_employee_invites_token_hash"),
    )
    op.create_index(
        "ix_employee_invites_employee_id",
        "employee_invites",
        ["employee_id"],
        unique=False,
    )

    op.create_table(
        "platform_audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("super_admin_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("company_id", sa.UUID(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["super_admin_id"],
            ["super_admins.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_audit_logs_action",
        "platform_audit_logs",
        ["action"],
        unique=False,
    )
    op.create_index(
        "ix_platform_audit_logs_company_id",
        "platform_audit_logs",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_platform_audit_logs_super_admin_id",
        "platform_audit_logs",
        ["super_admin_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_platform_audit_logs_super_admin_id", table_name="platform_audit_logs")
    op.drop_index("ix_platform_audit_logs_company_id", table_name="platform_audit_logs")
    op.drop_index("ix_platform_audit_logs_action", table_name="platform_audit_logs")
    op.drop_table("platform_audit_logs")

    op.drop_index("ix_employee_invites_employee_id", table_name="employee_invites")
    op.drop_table("employee_invites")

    op.drop_index(
        "ix_subscription_history_events_company_id",
        table_name="subscription_history_events",
    )
    op.drop_table("subscription_history_events")

    op.drop_index(
        "ix_company_subscriptions_company_id_is_current",
        table_name="company_subscriptions",
    )
    op.drop_index("ix_company_subscriptions_company_id", table_name="company_subscriptions")
    op.drop_table("company_subscriptions")

    op.drop_column("employees", "last_login_at")
    op.drop_column("employees", "password_hash")

    op.drop_column("companies", "contact_person")
    op.drop_column("companies", "contact_phone")
    op.drop_column("companies", "contact_email")
    op.drop_column("companies", "logo_url")
    op.drop_column("companies", "description")
