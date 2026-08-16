"""AI-6: rewrite knowledge_article_chunks.embedding as vector(1536).

Revision ID: e1f2a3b4c5d6
Revises: e0f1a2b3c4d5
Create Date: 2026-08-16

Chunk rows are derived data. Existing vector(8) fake embeddings cannot be
recast to 1536 dimensions, so they are deleted. Operators must reindex
current published articles after upgrade
(``POST /api/v1/knowledge/articles/reindex-published`` or
``python -m scripts.reindex_published_kb``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_article_chunks"


def upgrade() -> None:
    op.execute(f'DELETE FROM "{_TABLE}"')
    op.execute(f'ALTER TABLE "{_TABLE}" DROP COLUMN embedding')
    op.execute(f'ALTER TABLE "{_TABLE}" ADD COLUMN embedding vector(1536) NOT NULL')


def downgrade() -> None:
    op.execute(f'DELETE FROM "{_TABLE}"')
    op.execute(f'ALTER TABLE "{_TABLE}" DROP COLUMN embedding')
    op.execute(f'ALTER TABLE "{_TABLE}" ADD COLUMN embedding vector(8) NOT NULL')
