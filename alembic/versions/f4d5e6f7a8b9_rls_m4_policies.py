"""SEC-R3 M4: ENABLE ROW LEVEL SECURITY + create policies.

Revision ID: f4d5e6f7a8b9
Revises: f3c4d5e6f7a8
Create Date: 2026-08-08
"""

from __future__ import annotations

from alembic import op

revision = "f4d5e6f7a8b9"
down_revision = "f3c4d5e6f7a8"
branch_labels = None
depends_on = None

_TENANT_TABLES = (
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
)


def _tenant_policy(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON "{table}"
        FOR ALL
        USING (app.is_platform() OR company_id = app.company_id())
        WITH CHECK (app.is_platform() OR company_id = app.company_id())
        """
    )


def upgrade() -> None:
    # companies — tenant root (id = company); INSERT/DELETE platform-only
    op.execute('ALTER TABLE "companies" ENABLE ROW LEVEL SECURITY')
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

    for table in _TENANT_TABLES:
        _tenant_policy(table)

    # employees — also allow auth bootstrap subject resolution
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "employees"')
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

    # company_subscriptions — tenant SELECT; platform write
    op.execute('ALTER TABLE "company_subscriptions" ENABLE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS tenant_select ON "company_subscriptions"')
    op.execute('DROP POLICY IF EXISTS platform_write ON "company_subscriptions"')
    op.execute(
        """
        CREATE POLICY tenant_select ON "company_subscriptions"
        FOR SELECT
        USING (app.is_platform() OR app.is_auth() OR company_id = app.company_id())
        """
    )
    op.execute(
        """
        CREATE POLICY platform_write ON "company_subscriptions"
        FOR ALL
        USING (app.is_platform())
        WITH CHECK (app.is_platform())
        """
    )

    # subscription_history_events
    op.execute('ALTER TABLE "subscription_history_events" ENABLE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS tenant_select ON "subscription_history_events"')
    op.execute('DROP POLICY IF EXISTS platform_write ON "subscription_history_events"')
    op.execute(
        """
        CREATE POLICY tenant_select ON "subscription_history_events"
        FOR SELECT
        USING (app.is_platform() OR company_id = app.company_id())
        """
    )
    op.execute(
        """
        CREATE POLICY platform_write ON "subscription_history_events"
        FOR ALL
        USING (app.is_platform())
        WITH CHECK (app.is_platform())
        """
    )

    # employee_invites — auth/platform only (never tenant dump)
    op.execute('ALTER TABLE "employee_invites" ENABLE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS auth_platform ON "employee_invites"')
    op.execute(
        """
        CREATE POLICY auth_platform ON "employee_invites"
        FOR ALL
        USING (app.is_platform() OR app.is_auth())
        WITH CHECK (app.is_platform() OR app.is_auth())
        """
    )

    # refresh_sessions — session/platform only
    op.execute('ALTER TABLE "refresh_sessions" ENABLE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS session_platform ON "refresh_sessions"')
    op.execute(
        """
        CREATE POLICY session_platform ON "refresh_sessions"
        FOR ALL
        USING (app.is_session() OR app.is_platform())
        WITH CHECK (app.is_session() OR app.is_platform())
        """
    )

    # super_admins
    op.execute('ALTER TABLE "super_admins" ENABLE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS auth_platform ON "super_admins"')
    op.execute(
        """
        CREATE POLICY auth_platform ON "super_admins"
        FOR SELECT
        USING (app.is_platform() OR app.is_auth())
        """
    )
    op.execute('DROP POLICY IF EXISTS platform_write ON "super_admins"')
    op.execute(
        """
        CREATE POLICY platform_write ON "super_admins"
        FOR ALL
        USING (app.is_platform())
        WITH CHECK (app.is_platform())
        """
    )

    # platform_audit_logs — platform only
    op.execute('ALTER TABLE "platform_audit_logs" ENABLE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS platform_only ON "platform_audit_logs"')
    op.execute(
        """
        CREATE POLICY platform_only ON "platform_audit_logs"
        FOR ALL
        USING (app.is_platform())
        WITH CHECK (app.is_platform())
        """
    )


def downgrade() -> None:
    tables_policies = (
        ("companies", ("companies_select", "companies_update", "companies_insert", "companies_delete")),
        ("employees", ("tenant_isolation",)),
        ("onboarding_programs", ("tenant_isolation",)),
        ("steps", ("tenant_isolation",)),
        ("assignments", ("tenant_isolation",)),
        ("progress", ("tenant_isolation",)),
        ("knowledge_categories", ("tenant_isolation",)),
        ("knowledge_tags", ("tenant_isolation",)),
        ("knowledge_articles", ("tenant_isolation",)),
        ("knowledge_article_versions", ("tenant_isolation",)),
        ("knowledge_article_tags", ("tenant_isolation",)),
        ("knowledge_article_links", ("tenant_isolation",)),
        ("ai_conversations", ("tenant_isolation",)),
        ("company_subscriptions", ("tenant_select", "platform_write")),
        ("subscription_history_events", ("tenant_select", "platform_write")),
        ("employee_invites", ("auth_platform",)),
        ("refresh_sessions", ("session_platform",)),
        ("super_admins", ("auth_platform", "platform_write")),
        ("platform_audit_logs", ("platform_only",)),
    )
    for table, policies in tables_policies:
        for policy in policies:
            op.execute(f'DROP POLICY IF EXISTS {policy} ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
