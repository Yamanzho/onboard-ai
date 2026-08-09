"""SEC-R3 M7: narrow auth_bootstrap RLS (pinned employee subject).

Removes blanket auth SELECT on companies/subscriptions and blanket
employees ALL under is_auth(). Auth employee access requires
app.auth_employee_id() to match the row id (SELECT/UPDATE only).

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision = "f7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.auth_employee_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT NULLIF(current_setting('app.auth_employee_id', true), '')::uuid;
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.auth_employee_id() TO PUBLIC")

    # companies — no auth_bootstrap (resolve employee → enter_tenant)
    op.execute('DROP POLICY IF EXISTS companies_select ON "companies"')
    op.execute(
        """
        CREATE POLICY companies_select ON "companies"
        FOR SELECT
        USING (app.is_platform() OR id = app.company_id())
        """
    )

    # company_subscriptions — no auth_bootstrap
    op.execute('DROP POLICY IF EXISTS tenant_select ON "company_subscriptions"')
    op.execute(
        """
        CREATE POLICY tenant_select ON "company_subscriptions"
        FOR SELECT
        USING (app.is_platform() OR company_id = app.company_id())
        """
    )

    # employees — tenant/platform ALL; auth SELECT/UPDATE only for pinned subject
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "employees"')
    op.execute('DROP POLICY IF EXISTS auth_subject_select ON "employees"')
    op.execute('DROP POLICY IF EXISTS auth_subject_update ON "employees"')
    op.execute(
        """
        CREATE POLICY tenant_isolation ON "employees"
        FOR ALL
        USING (app.is_platform() OR company_id = app.company_id())
        WITH CHECK (app.is_platform() OR company_id = app.company_id())
        """
    )
    op.execute(
        """
        CREATE POLICY auth_subject_select ON "employees"
        FOR SELECT
        USING (
            app.is_auth()
            AND app.auth_employee_id() IS NOT NULL
            AND id = app.auth_employee_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY auth_subject_update ON "employees"
        FOR UPDATE
        USING (
            app.is_auth()
            AND app.auth_employee_id() IS NOT NULL
            AND id = app.auth_employee_id()
        )
        WITH CHECK (
            app.is_auth()
            AND app.auth_employee_id() IS NOT NULL
            AND id = app.auth_employee_id()
        )
        """
    )

    # employee_invites — auth may SELECT/UPDATE for token flows; INSERT/DELETE platform
    op.execute('DROP POLICY IF EXISTS auth_platform ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS auth_select ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS auth_update ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS platform_insert ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS platform_delete ON "employee_invites"')
    op.execute(
        """
        CREATE POLICY auth_select ON "employee_invites"
        FOR SELECT
        USING (app.is_platform() OR app.is_auth())
        """
    )
    op.execute(
        """
        CREATE POLICY auth_update ON "employee_invites"
        FOR UPDATE
        USING (app.is_platform() OR app.is_auth())
        WITH CHECK (app.is_platform() OR app.is_auth())
        """
    )
    op.execute(
        """
        CREATE POLICY platform_insert ON "employee_invites"
        FOR INSERT
        WITH CHECK (app.is_platform())
        """
    )
    op.execute(
        """
        CREATE POLICY platform_delete ON "employee_invites"
        FOR DELETE
        USING (app.is_platform())
        """
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS auth_select ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS auth_update ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS platform_insert ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS platform_delete ON "employee_invites"')
    op.execute(
        """
        CREATE POLICY auth_platform ON "employee_invites"
        FOR ALL
        USING (app.is_platform() OR app.is_auth())
        WITH CHECK (app.is_platform() OR app.is_auth())
        """
    )

    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "employees"')
    op.execute('DROP POLICY IF EXISTS auth_subject_select ON "employees"')
    op.execute('DROP POLICY IF EXISTS auth_subject_update ON "employees"')
    op.execute(
        """
        CREATE POLICY tenant_isolation ON "employees"
        FOR ALL
        USING (
            app.is_platform()
            OR app.is_auth()
            OR company_id = app.company_id()
        )
        WITH CHECK (
            app.is_platform()
            OR app.is_auth()
            OR company_id = app.company_id()
        )
        """
    )

    op.execute('DROP POLICY IF EXISTS tenant_select ON "company_subscriptions"')
    op.execute(
        """
        CREATE POLICY tenant_select ON "company_subscriptions"
        FOR SELECT
        USING (app.is_platform() OR app.is_auth() OR company_id = app.company_id())
        """
    )

    op.execute('DROP POLICY IF EXISTS companies_select ON "companies"')
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

    op.execute("DROP FUNCTION IF EXISTS app.auth_employee_id()")
