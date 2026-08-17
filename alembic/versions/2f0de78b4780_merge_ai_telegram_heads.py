"""merge_ai_telegram_heads

Revision ID: 2f0de78b4780
Revises: a7b8c9d0e1f2, f3a4b5c6d7e8
Create Date: 2026-08-18 00:22:27.545300

Empty merge of independent Telegram and AI Alembic heads.
No schema SQL.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "2f0de78b4780"
down_revision: str | Sequence[str] | None = (
    "a7b8c9d0e1f2",
    "f3a4b5c6d7e8",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
