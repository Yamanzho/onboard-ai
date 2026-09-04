"""Phase 9C: assignment priority, source_batch_id, ordering indexes.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "a9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column(
            "priority",
            sa.String(length=32),
            nullable=False,
            server_default="normal",
        ),
    )
    op.add_column(
        "assignments",
        sa.Column("source_batch_id", sa.UUID(), nullable=True),
    )
    op.create_check_constraint(
        "ck_assignments_priority",
        "assignments",
        "priority IN ('normal', 'important', 'critical')",
    )
    op.create_index(
        "ix_assignments_company_id_priority_due_at",
        "assignments",
        ["company_id", "priority", "due_at"],
        unique=False,
    )
    op.create_index(
        "ix_assignments_employee_id_priority_due_at",
        "assignments",
        ["employee_id", "priority", "due_at"],
        unique=False,
    )
    op.create_index(
        "ix_assignments_source_batch_id",
        "assignments",
        ["source_batch_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assignments_source_batch_id", table_name="assignments")
    op.drop_index(
        "ix_assignments_employee_id_priority_due_at",
        table_name="assignments",
    )
    op.drop_index(
        "ix_assignments_company_id_priority_due_at",
        table_name="assignments",
    )
    op.drop_constraint("ck_assignments_priority", "assignments", type_="check")
    op.drop_column("assignments", "source_batch_id")
    op.drop_column("assignments", "priority")
