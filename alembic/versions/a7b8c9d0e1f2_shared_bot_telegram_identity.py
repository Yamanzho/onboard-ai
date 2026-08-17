"""Shared Telegram bot: global active identity + auth pin.

One Telegram user id may authenticate at most one ACTIVE employee across
all tenants. Invited/archived rows are excluded so placeholder Web ids
and historical archives do not block a later real bind.

Identity lookup uses platform SELECT (same class as email login), not
BOT_COMPANY_ID. Optional RLS pin app.auth_telegram_user_id is available
for narrower SELECT. Duplicate active rows are reported — never deleted.

Revision ID: a7b8c9d0e1f2
Revises: c8d9e0f1a2b3
Create Date: 2026-08-17

Unreleased local revision. Parent is production Alembic head c8d9e0f1a2b3
(employee email unique). SQL only touches employees + RLS helpers; it does
not require later AI/pgvector revisions.
"""

from __future__ import annotations

from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fail closed if the same Telegram id is already active in more than one
    # company. Operators must inspect and resolve; this migration never
    # deletes or reassigns employee rows.
    op.execute(
        """
        DO $$
        DECLARE
          dup_ids text;
        BEGIN
          SELECT string_agg(telegram_user_id::text, ', ' ORDER BY telegram_user_id)
          INTO dup_ids
          FROM (
            SELECT telegram_user_id
            FROM employees
            WHERE status = 'active'
            GROUP BY telegram_user_id
            HAVING count(*) > 1
          ) d;

          IF dup_ids IS NOT NULL THEN
            RAISE EXCEPTION
              'Cannot add uq_employees_active_telegram_user_id: duplicate active telegram_user_id values exist (%). Resolve duplicates before migrating; do not delete rows automatically.',
              dup_ids;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_employees_active_telegram_user_id
        ON employees (telegram_user_id)
        WHERE status = 'active'
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.auth_telegram_user_id()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT NULLIF(current_setting('app.auth_telegram_user_id', true), '')::bigint;
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.auth_telegram_user_id() TO PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.auth_telegram_user_id() TO onboard_app"
    )

    op.execute('DROP POLICY IF EXISTS auth_telegram_select ON "employees"')
    op.execute(
        """
        CREATE POLICY auth_telegram_select ON "employees"
        FOR SELECT
        USING (
            app.is_auth()
            AND app.auth_telegram_user_id() IS NOT NULL
            AND telegram_user_id = app.auth_telegram_user_id()
        )
        """
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS auth_telegram_select ON "employees"')
    op.execute("DROP FUNCTION IF EXISTS app.auth_telegram_user_id()")
    op.execute("DROP INDEX IF EXISTS uq_employees_active_telegram_user_id")
