"""Tenant audit logs + knowledge article full-text search index.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-08-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("actor_employee_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["actor_employee_id"],
            ["employees.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_audit_logs_company_id",
        "company_audit_logs",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_company_audit_logs_action",
        "company_audit_logs",
        ["action"],
        unique=False,
    )
    op.create_index(
        "ix_company_audit_logs_actor_employee_id",
        "company_audit_logs",
        ["actor_employee_id"],
        unique=False,
    )
    op.create_index(
        "ix_company_audit_logs_company_id_created_at",
        "company_audit_logs",
        ["company_id", "created_at"],
        unique=False,
    )

    op.execute('ALTER TABLE "company_audit_logs" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "company_audit_logs" FORCE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "company_audit_logs"')
    op.execute(
        """
        CREATE POLICY tenant_isolation ON "company_audit_logs"
        FOR ALL
        USING (app.is_platform() OR company_id = app.company_id())
        WITH CHECK (app.is_platform() OR company_id = app.company_id())
        """
    )

    conn = op.get_bind()
    owner_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_owner'")
    ).scalar()
    app_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_app'")
    ).scalar()
    if owner_exists:
        op.execute('ALTER TABLE "company_audit_logs" OWNER TO onboard_owner')
    if app_exists:
        op.execute(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "company_audit_logs" '
            "TO onboard_app"
        )

    op.execute(
        """
        CREATE INDEX ix_knowledge_article_versions_fts
        ON knowledge_article_versions
        USING gin (
            to_tsvector(
                'simple',
                coalesce(title, '') || ' ' || coalesce(body, '')
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_article_versions_fts")
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "company_audit_logs"')
    op.drop_index(
        "ix_company_audit_logs_company_id_created_at",
        table_name="company_audit_logs",
    )
    op.drop_index("ix_company_audit_logs_actor_employee_id", table_name="company_audit_logs")
    op.drop_index("ix_company_audit_logs_action", table_name="company_audit_logs")
    op.drop_index("ix_company_audit_logs_company_id", table_name="company_audit_logs")
    op.drop_table("company_audit_logs")
