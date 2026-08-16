"""AI-2: pgvector extension + knowledge_article_chunks with tenant RLS.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: str | Sequence[str] | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_article_chunks"


def upgrade() -> None:
    # Bootstrap (superuser) also creates this; IF NOT EXISTS keeps Alembic
    # idempotent when onboard_owner is not allowed to CREATE EXTENSION.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # AI-2 test width. AI-6 migrates this column to vector(1536).
        sa.Column("embedding", Vector(8), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_article_chunks_chunk_index_non_negative",
        ),
        sa.CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_knowledge_article_chunks_content_not_blank",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["knowledge_articles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_article_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "version_id",
            "chunk_index",
            name="uq_knowledge_article_chunks_version_id_chunk_index",
        ),
    )
    op.create_index(
        "ix_knowledge_article_chunks_company_id",
        _TABLE,
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_article_chunks_version_id",
        _TABLE,
        ["version_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_article_chunks_article_id",
        _TABLE,
        ["article_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_article_chunks_company_id_article_id",
        _TABLE,
        ["company_id", "article_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_article_chunks_company_id_version_id",
        _TABLE,
        ["company_id", "version_id"],
        unique=False,
    )

    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{_TABLE}"')
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON "{_TABLE}"
        FOR ALL
        USING (app.is_platform() OR company_id = app.company_id())
        WITH CHECK (app.is_platform() OR company_id = app.company_id())
        """
    )

    conn = op.get_bind()
    owner_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_owner'")
    ).scalar()
    app_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_app'")
    ).scalar()
    if owner_exists:
        op.execute(f'ALTER TABLE "{_TABLE}" OWNER TO onboard_owner')
    if app_exists:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{_TABLE}" TO onboard_app'
        )


def downgrade() -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{_TABLE}"')
    op.drop_index(
        "ix_knowledge_article_chunks_company_id_version_id",
        table_name=_TABLE,
    )
    op.drop_index(
        "ix_knowledge_article_chunks_company_id_article_id",
        table_name=_TABLE,
    )
    op.drop_index("ix_knowledge_article_chunks_article_id", table_name=_TABLE)
    op.drop_index("ix_knowledge_article_chunks_version_id", table_name=_TABLE)
    op.drop_index("ix_knowledge_article_chunks_company_id", table_name=_TABLE)
    op.drop_table(_TABLE)
    # Leave the vector extension installed — other objects may depend on it,
    # and bootstrap recreates it if needed.
