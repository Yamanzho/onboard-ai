"""Allow password_reset invite purpose.

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-08-09

Extends ck_employee_invites_purpose so Admin/HR can issue one-time
password-reset tokens for ACTIVE employees without weakening onboarding
invite purpose/role mapping.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_employee_invites_purpose", "employee_invites", type_="check")
    op.create_check_constraint(
        "ck_employee_invites_purpose",
        "employee_invites",
        "purpose IN ('employee', 'hr', 'admin', 'password_reset')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE employee_invites SET used_at = COALESCE(used_at, now()) "
        "WHERE purpose = 'password_reset' AND used_at IS NULL"
    )
    op.execute("DELETE FROM employee_invites WHERE purpose = 'password_reset'")
    op.drop_constraint("ck_employee_invites_purpose", "employee_invites", type_="check")
    op.create_check_constraint(
        "ck_employee_invites_purpose",
        "employee_invites",
        "purpose IN ('employee', 'hr', 'admin')",
    )
