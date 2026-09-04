"""Phase 9D: course revision and assignment revision snapshot.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "onboarding_programs",
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_onboarding_programs_revision_positive",
        "onboarding_programs",
        "revision >= 1",
    )
    op.add_column(
        "assignments",
        sa.Column(
            "program_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_assignments_program_revision_positive",
        "assignments",
        "program_revision >= 1",
    )
    op.create_index(
        "ix_assignments_program_id_status",
        "assignments",
        ["program_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assignments_program_id_status", table_name="assignments")
    op.drop_constraint(
        "ck_assignments_program_revision_positive",
        "assignments",
        type_="check",
    )
    op.drop_column("assignments", "program_revision")
    op.drop_constraint(
        "ck_onboarding_programs_revision_positive",
        "onboarding_programs",
        type_="check",
    )
    op.drop_column("onboarding_programs", "revision")
