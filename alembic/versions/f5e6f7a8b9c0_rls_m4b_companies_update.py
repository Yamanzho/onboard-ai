"""SEC-R3 M4b: fix companies UPDATE policy for tenant settings edits.

Tenant admins must UPDATE their own company row (settings/profile).
INSERT/DELETE remain platform-only.

Revision ID: f5e6f7a8b9c0
Revises: f4d5e6f7a8b9
Create Date: 2026-08-08
"""

from __future__ import annotations

from alembic import op

revision = "f5e6f7a8b9c0"
down_revision = "f4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "companies"')
    op.execute('DROP POLICY IF EXISTS companies_select ON "companies"')
    op.execute('DROP POLICY IF EXISTS companies_update ON "companies"')
    op.execute('DROP POLICY IF EXISTS companies_insert ON "companies"')
    op.execute('DROP POLICY IF EXISTS companies_delete ON "companies"')
    op.execute(
        """
        CREATE POLICY companies_select ON "companies"
        FOR SELECT
        USING (
            app.is_platform()
            OR app.is_auth()
            OR id = app.company_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY companies_update ON "companies"
        FOR UPDATE
        USING (app.is_platform() OR id = app.company_id())
        WITH CHECK (app.is_platform() OR id = app.company_id())
        """
    )
    op.execute(
        """
        CREATE POLICY companies_insert ON "companies"
        FOR INSERT
        WITH CHECK (app.is_platform())
        """
    )
    op.execute(
        """
        CREATE POLICY companies_delete ON "companies"
        FOR DELETE
        USING (app.is_platform())
        """
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS companies_select ON "companies"')
    op.execute('DROP POLICY IF EXISTS companies_update ON "companies"')
    op.execute('DROP POLICY IF EXISTS companies_insert ON "companies"')
    op.execute('DROP POLICY IF EXISTS companies_delete ON "companies"')
    op.execute(
        """
        CREATE POLICY tenant_isolation ON "companies"
        FOR ALL
        USING (
            app.is_platform()
            OR app.is_auth()
            OR id = app.company_id()
        )
        WITH CHECK (app.is_platform())
        """
    )
