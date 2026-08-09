"""SEC-R3 M9: allow invite SELECT under auth employee pin (F-01).

PostgreSQL applies SELECT policies when evaluating UPDATE candidates.
Sibling invite invalidate after accept pins auth_employee_id only; without a
matching SELECT policy those UPDATEs match zero rows. Token-hash SELECT
remains required for unpinned / cross-invite access.

Revision ID: f9d0e1f2a3b4
Revises: f8c9d0e1f2a3
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision = "f9d0e1f2a3b4"
down_revision = "f8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('DROP POLICY IF EXISTS auth_select ON "employee_invites"')
    op.execute(
        """
        CREATE POLICY auth_select ON "employee_invites"
        FOR SELECT
        USING (
            app.is_platform()
            OR (
                app.is_auth()
                AND (
                    (
                        app.auth_invite_token_hash() IS NOT NULL
                        AND token_hash = app.auth_invite_token_hash()
                    )
                    OR (
                        app.auth_employee_id() IS NOT NULL
                        AND employee_id = app.auth_employee_id()
                    )
                )
            )
        )
        """
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS auth_select ON "employee_invites"')
    op.execute(
        """
        CREATE POLICY auth_select ON "employee_invites"
        FOR SELECT
        USING (
            app.is_platform()
            OR (
                app.is_auth()
                AND app.auth_invite_token_hash() IS NOT NULL
                AND token_hash = app.auth_invite_token_hash()
            )
        )
        """
    )
