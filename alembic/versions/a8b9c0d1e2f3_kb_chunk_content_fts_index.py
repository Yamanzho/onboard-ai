"""AI-hybrid-1: GIN full-text search index on knowledge_article_chunks.content.

Enables lexical retrieval in the hybrid vector + FTS retrieval pipeline.
Uses the 'simple' text-search configuration (no language-specific stemming)
so that Russian proper names such as "Евгений", "Джумадуллаева", "Омарова"
are tokenised and matched exactly.

CREATE INDEX CONCURRENTLY cannot run inside a transaction, so this migration
uses Alembic's autocommit_block context manager rather than a raw COMMIT.

Revision ID: a8b9c0d1e2f3
Revises: 2f0de78b4780
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | Sequence[str] | None = "2f0de78b4780"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_knowledge_article_chunks_content_fts"
_TABLE = "knowledge_article_chunks"


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY must run outside an explicit transaction.
    # Alembic's autocommit_block commits any pending work, issues the DDL in
    # autocommit mode, then returns to the normal connection state.
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX}
            ON {_TABLE}
            USING gin (to_tsvector('simple', content))
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
