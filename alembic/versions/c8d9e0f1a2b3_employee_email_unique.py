"""Unique employee email for web login resolution.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-08-09

Web login uses email + password without a company selector. Non-null emails
must therefore resolve to at most one employee row. Telegram-only employees
may keep email NULL (excluded from the unique index).

Strategy chosen after audit: global uniqueness of lower(email) where present
— not per-company alone — because per-company uniqueness leaves cross-tenant
ambiguity for email-only login. UUID remains the primary key.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fail closed if legacy duplicates exist — operator must clean them first.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM (
                    SELECT lower(btrim(email)) AS e
                    FROM employees
                    WHERE email IS NOT NULL AND btrim(email) <> ''
                    GROUP BY 1
                    HAVING count(*) > 1
                ) d
            ) THEN
                RAISE EXCEPTION
                    'Cannot add uq_employees_email_lower: duplicate emails exist';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_employees_email_lower
        ON employees (lower(btrim(email)))
        WHERE email IS NOT NULL AND btrim(email) <> ''
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_employees_email_lower")
