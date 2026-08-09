"""Add invite purpose for unified EMPLOYEE/HR/ADMIN invitations.

Revision ID: a6b7c8d9e0f1
Revises: f9d0e1f2a3b4
Create Date: 2026-08-09 15:00:00.000000

Invite rows remain platform/auth RLS only (no tenant dump of token hashes).
Tenant HR/Admin create flows call InviteService, which writes under platform RLS
after the employee row was created in tenant mode.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop tenant policies if a prior draft of this revision added them.
    op.execute('DROP POLICY IF EXISTS tenant_select ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS tenant_insert ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS tenant_update ON "employee_invites"')

    op.add_column(
        "employee_invites",
        sa.Column("purpose", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE employee_invites AS i
        SET purpose = e.role
        FROM employees AS e
        WHERE i.employee_id = e.id
        """
    )
    op.execute(
        """
        UPDATE employee_invites
        SET purpose = 'employee'
        WHERE purpose IS NULL
        """
    )
    op.alter_column("employee_invites", "purpose", nullable=False)
    op.create_check_constraint(
        "ck_employee_invites_purpose",
        "employee_invites",
        "purpose IN ('employee', 'hr', 'admin')",
    )
    op.create_index(
        "ix_employee_invites_purpose",
        "employee_invites",
        ["purpose"],
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_select ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS tenant_insert ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS tenant_update ON "employee_invites"')
    op.drop_index("ix_employee_invites_purpose", table_name="employee_invites")
    op.drop_constraint("ck_employee_invites_purpose", "employee_invites", type_="check")
    op.drop_column("employee_invites", "purpose")
