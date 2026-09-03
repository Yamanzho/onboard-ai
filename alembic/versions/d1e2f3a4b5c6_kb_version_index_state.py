"""Phase 7E: durable knowledge-version indexing state.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_article_versions"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "index_status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(_TABLE, sa.Column("embedding_provider", sa.String(length=64)))
    op.add_column(_TABLE, sa.Column("embedding_model", sa.String(length=255)))
    op.add_column(_TABLE, sa.Column("embedding_dimension", sa.Integer()))
    op.add_column(_TABLE, sa.Column("indexed_chunk_count", sa.Integer()))
    op.add_column(_TABLE, sa.Column("indexing_started_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("indexed_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("indexing_failed_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("failure_category", sa.String(length=64)))
    op.add_column(_TABLE, sa.Column("indexing_owner_token", sa.UUID()))
    op.add_column(
        _TABLE,
        sa.Column("indexing_lease_expires_at", sa.DateTime(timezone=True)),
    )

    op.create_check_constraint(
        "ck_knowledge_article_versions_index_status",
        _TABLE,
        "index_status IN ('pending', 'indexing', 'indexed', 'failed')",
    )
    op.create_check_constraint(
        "ck_knowledge_article_versions_embedding_dimension_positive",
        _TABLE,
        "embedding_dimension IS NULL OR embedding_dimension > 0",
    )
    op.create_check_constraint(
        "ck_knowledge_article_versions_indexed_chunk_count_positive",
        _TABLE,
        "indexed_chunk_count IS NULL OR indexed_chunk_count > 0",
    )
    op.create_check_constraint(
        "ck_knowledge_article_versions_indexing_lease_pair",
        _TABLE,
        "(indexing_owner_token IS NULL) = (indexing_lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_knowledge_article_versions_indexed_metadata",
        _TABLE,
        "index_status <> 'indexed' OR "
        "(embedding_provider IS NOT NULL AND embedding_model IS NOT NULL "
        "AND embedding_dimension IS NOT NULL AND indexed_chunk_count IS NOT NULL "
        "AND indexed_at IS NOT NULL)",
    )
    op.create_index(
        "ix_knowledge_article_versions_company_id_index_status",
        _TABLE,
        ["company_id", "index_status"],
    )

    # Existing indexer writes one transactionally complete, contiguous chunk
    # set and records the model on every row. Only recognize providers/models
    # that can be identified without guessing; all other versions stay pending.
    op.execute(
        """
        WITH proven AS (
            SELECT
                version_id,
                count(*)::integer AS chunk_count,
                min(chunk_index) AS min_chunk_index,
                max(chunk_index) AS max_chunk_index,
                count(DISTINCT metadata->>'embedding_model') AS model_count,
                count(metadata->>'embedding_model') AS model_value_count,
                min(metadata->>'embedding_model') AS embedding_model,
                bool_and(vector_dims(embedding) = 1536) AS dimension_ok,
                max(updated_at) AS indexed_at
            FROM knowledge_article_chunks
            GROUP BY version_id
        )
        UPDATE knowledge_article_versions AS version
        SET
            index_status = 'indexed',
            embedding_provider = CASE
                WHEN proven.embedding_model = 'fake' THEN 'fake'
                WHEN proven.embedding_model = 'text-embedding-3-small' THEN 'openai'
            END,
            embedding_model = proven.embedding_model,
            embedding_dimension = 1536,
            indexed_chunk_count = proven.chunk_count,
            indexed_at = proven.indexed_at
        FROM proven
        WHERE version.id = proven.version_id
          AND proven.chunk_count > 0
          AND proven.min_chunk_index = 0
          AND proven.max_chunk_index = proven.chunk_count - 1
          AND proven.model_count = 1
          AND proven.model_value_count = proven.chunk_count
          AND proven.dimension_ok
          AND proven.embedding_model IN ('fake', 'text-embedding-3-small')
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_article_versions_company_id_index_status",
        table_name=_TABLE,
    )
    for constraint in (
        "ck_knowledge_article_versions_indexed_metadata",
        "ck_knowledge_article_versions_indexing_lease_pair",
        "ck_knowledge_article_versions_indexed_chunk_count_positive",
        "ck_knowledge_article_versions_embedding_dimension_positive",
        "ck_knowledge_article_versions_index_status",
    ):
        op.drop_constraint(constraint, _TABLE, type_="check")
    for column in (
        "indexing_lease_expires_at",
        "indexing_owner_token",
        "failure_category",
        "indexing_failed_at",
        "indexed_at",
        "indexing_started_at",
        "indexed_chunk_count",
        "embedding_dimension",
        "embedding_model",
        "embedding_provider",
        "index_status",
    ):
        op.drop_column(_TABLE, column)
