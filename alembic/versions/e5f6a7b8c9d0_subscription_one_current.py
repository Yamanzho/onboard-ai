"""Guarantee at most one current subscription per company (P0-06).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-08 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Matches get_current_for_company(): newest created_at wins; id breaks ties.
_NORMALIZE_DUPLICATE_CURRENTS = sa.text(
    """
    WITH ranked AS (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY company_id
                ORDER BY created_at DESC, id DESC
            ) AS rn
        FROM company_subscriptions
        WHERE is_current IS TRUE
    )
    UPDATE company_subscriptions AS cs
    SET is_current = FALSE
    FROM ranked
    WHERE cs.id = ranked.id
      AND ranked.rn > 1
    """
)


def upgrade() -> None:
    # Safe, deterministic cleanup before enforcing uniqueness.
    # Keeps the newest current row per company (created_at DESC, id DESC);
    # demotes older duplicate currents to historical (is_current=false).
    # Does not delete subscription rows.
    op.execute(_NORMALIZE_DUPLICATE_CURRENTS)

    op.drop_index(
        "ix_company_subscriptions_company_id_is_current",
        table_name="company_subscriptions",
    )
    op.create_index(
        "uq_company_subscriptions_company_id_current",
        "company_subscriptions",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("is_current IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_company_subscriptions_company_id_current",
        table_name="company_subscriptions",
    )
    op.create_index(
        "ix_company_subscriptions_company_id_is_current",
        "company_subscriptions",
        ["company_id", "is_current"],
        unique=False,
    )
