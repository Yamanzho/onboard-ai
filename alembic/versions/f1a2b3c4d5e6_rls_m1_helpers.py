"""SEC-R3 M1: RLS helper functions (transaction-local GUC readers).

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-08-08
"""

from __future__ import annotations

from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.company_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT NULLIF(current_setting('app.current_company_id', true), '')::uuid;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.is_platform()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT current_setting('app.platform_admin', true) = 'on';
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.is_auth()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT current_setting('app.auth_mode', true) = 'bootstrap';
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.is_session()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT current_setting('app.session_mode', true) = 'bootstrap';
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA app TO PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.company_id(), app.is_platform(), "
        "app.is_auth(), app.is_session() TO PUBLIC"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.is_session()")
    op.execute("DROP FUNCTION IF EXISTS app.is_auth()")
    op.execute("DROP FUNCTION IF EXISTS app.is_platform()")
    op.execute("DROP FUNCTION IF EXISTS app.company_id()")
    op.execute("DROP SCHEMA IF EXISTS app CASCADE")
