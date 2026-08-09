"""SEC-R3 M8: pin auth_bootstrap for invites and super_admins (F-01).

Narrows employee_invites and super_admins so auth_bootstrap cannot
SELECT/UPDATE all rows. Invite access requires app.auth_invite_token_hash()
(or employee_id pin for sibling invalidate). Super Admin SELECT requires
app.auth_super_admin_id() or app.auth_super_admin_email().

Revision ID: f8c9d0e1f2a3
Revises: f7b8c9d0e1f2
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision = "f8c9d0e1f2a3"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.auth_invite_token_hash()
        RETURNS text
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT NULLIF(current_setting('app.auth_invite_token_hash', true), '');
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.auth_super_admin_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT NULLIF(current_setting('app.auth_super_admin_id', true), '')::uuid;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.auth_super_admin_email()
        RETURNS text
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT NULLIF(lower(current_setting('app.auth_super_admin_email', true)), '');
        $$
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.auth_invite_token_hash(), "
        "app.auth_super_admin_id(), app.auth_super_admin_email() TO PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.auth_invite_token_hash(), "
        "app.auth_super_admin_id(), app.auth_super_admin_email() TO onboard_app"
    )

    # employee_invites — auth SELECT only by pinned token_hash; UPDATE by
    # token_hash or pinned employee_id (sibling invalidate after accept).
    op.execute('DROP POLICY IF EXISTS auth_select ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS auth_update ON "employee_invites"')
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
    op.execute(
        """
        CREATE POLICY auth_update ON "employee_invites"
        FOR UPDATE
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
        WITH CHECK (
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

    # super_admins — auth SELECT only for pinned id or email (login / JWT).
    op.execute('DROP POLICY IF EXISTS auth_platform ON "super_admins"')
    op.execute(
        """
        CREATE POLICY auth_subject_select ON "super_admins"
        FOR SELECT
        USING (
            app.is_platform()
            OR (
                app.is_auth()
                AND (
                    (
                        app.auth_super_admin_id() IS NOT NULL
                        AND id = app.auth_super_admin_id()
                    )
                    OR (
                        app.auth_super_admin_email() IS NOT NULL
                        AND email = app.auth_super_admin_email()
                    )
                )
            )
        )
        """
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS auth_subject_select ON "super_admins"')
    op.execute(
        """
        CREATE POLICY auth_platform ON "super_admins"
        FOR SELECT
        USING (app.is_platform() OR app.is_auth())
        """
    )

    op.execute('DROP POLICY IF EXISTS auth_select ON "employee_invites"')
    op.execute('DROP POLICY IF EXISTS auth_update ON "employee_invites"')
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

    op.execute("DROP FUNCTION IF EXISTS app.auth_super_admin_email()")
    op.execute("DROP FUNCTION IF EXISTS app.auth_super_admin_id()")
    op.execute("DROP FUNCTION IF EXISTS app.auth_invite_token_hash()")
