"""Phase 7D: durable Telegram outbound outbox.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | Sequence[str] | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "telegram_outbound_messages"


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
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("parse_mode", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("last_error_category", sa.String(length=32), nullable=True),
        sa.Column("owner_token", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "source_type IN ('ai_chat', 'quiz_result')",
            name="ck_telegram_outbound_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed')",
            name="ck_telegram_outbound_status",
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4096",
            name="ck_telegram_outbound_body_length",
        ),
        sa.CheckConstraint(
            "parse_mode IS NULL OR parse_mode = 'HTML'",
            name="ck_telegram_outbound_parse_mode",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_telegram_outbound_attempt_count",
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
            "source_type",
            "source_key",
            name="uq_telegram_outbound_source",
        ),
    )
    op.create_index(
        "ix_telegram_outbound_due",
        _TABLE,
        ["next_attempt_at", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_telegram_outbound_stale_sending",
        _TABLE,
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'sending'"),
    )
    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY tenant_or_platform ON "{_TABLE}"
        FOR ALL
        USING (
            app.is_platform()
            OR company_id = app.company_id()
        )
        WITH CHECK (
            app.is_platform()
            OR company_id = app.company_id()
        )
        """
    )
    _grant_app_table()


def downgrade() -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_or_platform ON "{_TABLE}"')
    op.drop_index("ix_telegram_outbound_stale_sending", table_name=_TABLE)
    op.drop_index("ix_telegram_outbound_due", table_name=_TABLE)
    op.drop_table(_TABLE)
