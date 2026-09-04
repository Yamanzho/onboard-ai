"""Phase 9G: assignment reminder preferences and outbox source types.

Revision ID: e4f5a6b7c8d9
Revises: d2e3f4a5b6c7
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "assignment_reminder_preferences"
_OUTBOX = "telegram_outbound_messages"
_SOURCE_TYPES = (
    "ai_chat",
    "quiz_result",
    "assignment_initial",
    "assignment_reminder",
    "assignment_manual_reminder",
)


def _protect_table(table: str) -> None:
    conn = op.get_bind()
    owner_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_owner'")
    ).scalar()
    app_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_app'")
    ).scalar()
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON "{table}"
        FOR ALL
        USING (app.is_platform() OR company_id = app.company_id())
        WITH CHECK (app.is_platform() OR company_id = app.company_id())
        """
    )
    if owner_exists:
        op.execute(f'ALTER TABLE "{table}" OWNER TO onboard_owner')
    if app_exists:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO onboard_app'
        )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="default"),
        sa.Column("acknowledged_until_date", sa.Date(), nullable=True),
        sa.Column("last_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_automated_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_manual_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_employee_at", sa.DateTime(timezone=True), nullable=True),
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
            "mode IN ('default', 'reduced', 'disabled')",
            name="ck_assignment_reminder_mode",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["assignments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", name="uq_assignment_reminder_assignment_id"),
    )
    op.create_index(
        "ix_assignment_reminder_preferences_company_id",
        _TABLE,
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_assignment_reminder_preferences_employee_id",
        _TABLE,
        ["employee_id"],
        unique=False,
    )
    _protect_table(_TABLE)

    op.drop_constraint(
        "ck_telegram_outbound_source_type",
        _OUTBOX,
        type_="check",
    )
    allowed = ", ".join(f"'{item}'" for item in _SOURCE_TYPES)
    op.create_check_constraint(
        "ck_telegram_outbound_source_type",
        _OUTBOX,
        f"source_type IN ({allowed})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_telegram_outbound_source_type",
        _OUTBOX,
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_outbound_source_type",
        _OUTBOX,
        "source_type IN ('ai_chat', 'quiz_result')",
    )
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{_TABLE}"')
    op.drop_index(
        "ix_assignment_reminder_preferences_employee_id",
        table_name=_TABLE,
    )
    op.drop_index(
        "ix_assignment_reminder_preferences_company_id",
        table_name=_TABLE,
    )
    op.drop_table(_TABLE)
