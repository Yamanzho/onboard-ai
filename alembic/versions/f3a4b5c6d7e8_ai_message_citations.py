"""AI-12B: persist public citations and no_answer on assistant messages.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-16

Stores only the public citation shape (source_id, title, article_id) plus
no_answer. Not ACL. Not retrieval metadata (scores, embeddings, version_id).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MESSAGES = "ai_messages"


def upgrade() -> None:
    op.add_column(
        _MESSAGES,
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        _MESSAGES,
        sa.Column(
            "no_answer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column(_MESSAGES, "no_answer")
    op.drop_column(_MESSAGES, "citations")
