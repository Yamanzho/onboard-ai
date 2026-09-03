"""Phase 7C: durable Telegram-update and AI-turn idempotency receipts.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str | Sequence[str] | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "idempotency_receipts"


def _grant_app_table() -> None:
    conn = op.get_bind()
    owner_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_owner'")
    ).scalar()
    app_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_app'")
    ).scalar()
    if owner_exists:
        op.execute(f'ALTER TABLE "{_TABLE}" OWNER TO onboard_owner')
    if app_exists:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{_TABLE}" TO onboard_app'
        )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("owner_token", sa.UUID(), nullable=True),
        sa.Column("company_id", sa.UUID(), nullable=True),
        sa.Column("employee_id", sa.UUID(), nullable=True),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('processing', 'completed', 'failed')",
            name="ck_idempotency_receipts_status",
        ),
        sa.CheckConstraint(
            "(company_id IS NULL) = (employee_id IS NULL)",
            name="ck_idempotency_receipts_identity_pair",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "operation",
            "idempotency_key",
            name="uq_idempotency_receipts_scope_operation_key",
        ),
    )
    op.create_index(
        "ix_idempotency_receipts_stale_processing",
        _TABLE,
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )

    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_or_platform ON "{_TABLE}"')
    op.execute(
        f"""
        CREATE POLICY tenant_or_platform ON "{_TABLE}"
        FOR ALL
        USING (
            app.is_platform()
            OR (
                company_id IS NOT NULL
                AND company_id = app.company_id()
            )
        )
        WITH CHECK (
            app.is_platform()
            OR (
                company_id IS NOT NULL
                AND company_id = app.company_id()
            )
        )
        """
    )
    _grant_app_table()


def downgrade() -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_or_platform ON "{_TABLE}"')
    op.drop_index(
        "ix_idempotency_receipts_stale_processing",
        table_name=_TABLE,
    )
    op.drop_table(_TABLE)
