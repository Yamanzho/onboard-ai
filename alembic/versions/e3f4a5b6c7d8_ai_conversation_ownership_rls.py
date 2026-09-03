"""Phase 7G: employee ownership RLS for AI conversations and messages.

Revision ID: e3f4a5b6c7d8
Revises: d1e2f3a4b5c6
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.employee_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT NULLIF(current_setting('app.current_employee_id', true), '')::uuid;
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.employee_id() TO PUBLIC")

    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "ai_conversations"')
    op.execute('DROP POLICY IF EXISTS employee_ownership ON "ai_conversations"')
    op.execute(
        """
        CREATE POLICY employee_ownership ON "ai_conversations"
        FOR ALL
        USING (
            company_id = app.company_id()
            AND app.employee_id() IS NOT NULL
            AND employee_id = app.employee_id()
        )
        WITH CHECK (
            company_id = app.company_id()
            AND app.employee_id() IS NOT NULL
            AND employee_id = app.employee_id()
        )
        """
    )

    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "ai_messages"')
    op.execute('DROP POLICY IF EXISTS employee_ownership ON "ai_messages"')
    op.execute(
        """
        CREATE POLICY employee_ownership ON "ai_messages"
        FOR ALL
        USING (
            company_id = app.company_id()
            AND app.employee_id() IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM ai_conversations AS conversation
                WHERE conversation.id = ai_messages.conversation_id
                  AND conversation.company_id = app.company_id()
                  AND conversation.employee_id = app.employee_id()
            )
        )
        WITH CHECK (
            company_id = app.company_id()
            AND app.employee_id() IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM ai_conversations AS conversation
                WHERE conversation.id = ai_messages.conversation_id
                  AND conversation.company_id = app.company_id()
                  AND conversation.employee_id = app.employee_id()
            )
        )
        """
    )

    op.execute('ALTER TABLE "ai_conversations" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "ai_conversations" FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "ai_messages" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "ai_messages" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in ("ai_messages", "ai_conversations"):
        op.execute(f'DROP POLICY IF EXISTS employee_ownership ON "{table}"')
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON "{table}"
            FOR ALL
            USING (app.is_platform() OR company_id = app.company_id())
            WITH CHECK (app.is_platform() OR company_id = app.company_id())
            """
        )
    op.execute("DROP FUNCTION IF EXISTS app.employee_id()")
