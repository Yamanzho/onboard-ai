"""SEC-R3 M2: table ownership + grants for onboard_owner / onboard_app.

Roles themselves are created by ``scripts.bootstrap_rls_roles`` (superuser).
This migration reassigns application table ownership and DML grants.

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

_TABLES = (
    "companies",
    "employees",
    "onboarding_programs",
    "steps",
    "assignments",
    "progress",
    "knowledge_categories",
    "knowledge_tags",
    "knowledge_articles",
    "knowledge_article_versions",
    "knowledge_article_tags",
    "knowledge_article_links",
    "ai_conversations",
    "company_subscriptions",
    "subscription_history_events",
    "employee_invites",
    "refresh_sessions",
    "super_admins",
    "platform_audit_logs",
    "alembic_version",
)


def upgrade() -> None:
    conn = op.get_bind()
    owner_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_owner'")
    ).scalar()
    app_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_app'")
    ).scalar()
    if not owner_exists or not app_exists:
        raise RuntimeError(
            "SEC-R3 roles missing. Run: python -m scripts.bootstrap_rls_roles "
            "(as PostgreSQL superuser) before this migration."
        )

    # BYPASSRLS / NOBYPASSRLS are set by bootstrap_rls_roles (requires superuser).
    op.execute("GRANT USAGE ON SCHEMA public TO onboard_app")
    op.execute("GRANT USAGE ON SCHEMA app TO onboard_app")
    op.execute("GRANT USAGE, CREATE ON SCHEMA public TO onboard_owner")

    for table in _TABLES:
        exists = conn.execute(
            sa.text("SELECT to_regclass(:name)"),
            {"name": f"public.{table}"},
        ).scalar()
        if exists is None:
            continue
        op.execute(f'ALTER TABLE "{table}" OWNER TO onboard_owner')
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO onboard_app'
        )

    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO onboard_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE onboard_owner IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO onboard_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE onboard_owner IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO onboard_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.company_id(), app.is_platform(), "
        "app.is_auth(), app.is_session() TO onboard_app"
    )


def downgrade() -> None:
    # Intentionally leave roles/ownership in place — reversing ownership without
    # knowing the previous owner is unsafe. Operators may REASSIGN OWNED manually.
    pass
