"""knowledge base foundation

Revision ID: a1b2c3d4e5f6
Revises: d08d8c8a7c9f
Create Date: 2026-08-04 23:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d08d8c8a7c9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- new taxonomy tables ---
    op.create_table(
        "knowledge_categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
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
            "position >= 0",
            name="ck_knowledge_categories_position_non_negative",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["knowledge_categories.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "slug",
            name="uq_knowledge_categories_company_id_slug",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_categories_company_id"),
        "knowledge_categories",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_categories_parent_id"),
        "knowledge_categories",
        ["parent_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_categories_company_id_parent_id",
        "knowledge_categories",
        ["company_id", "parent_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_tags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "slug",
            name="uq_knowledge_tags_company_id_slug",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_tags_company_id"),
        "knowledge_tags",
        ["company_id"],
        unique=False,
    )

    # --- evolve knowledge_articles: add new columns (keep legacy during backfill) ---
    op.add_column(
        "knowledge_articles",
        sa.Column("category_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("current_version_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "visibility",
            sa.String(length=32),
            nullable=False,
            server_default="company",
        ),
    )
    op.create_foreign_key(
        "fk_knowledge_articles_category_id",
        "knowledge_articles",
        "knowledge_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_knowledge_articles_status",
        "knowledge_articles",
        "status IN ('draft', 'published', 'archived')",
    )
    op.create_check_constraint(
        "ck_knowledge_articles_visibility",
        "knowledge_articles",
        "visibility IN ('company', 'program')",
    )
    op.create_index(
        "ix_knowledge_articles_company_id_status",
        "knowledge_articles",
        ["company_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_articles_category_id",
        "knowledge_articles",
        ["category_id"],
        unique=False,
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )

    # --- versions (content snapshots) ---
    op.create_table(
        "knowledge_article_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "body_format",
            sa.String(length=32),
            nullable=False,
            server_default="markdown",
        ),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
            "version >= 1",
            name="ck_knowledge_article_versions_version_positive",
        ),
        sa.CheckConstraint(
            "body_format IN ('markdown', 'html', 'plain')",
            name="ck_knowledge_article_versions_body_format",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["knowledge_articles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["employees.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id",
            "version",
            name="uq_knowledge_article_versions_article_id_version",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_article_versions_article_id"),
        "knowledge_article_versions",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_versions_created_by_id"),
        "knowledge_article_versions",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_article_versions_article_id_version",
        "knowledge_article_versions",
        ["article_id", "version"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_knowledge_articles_current_version_id",
        "knowledge_articles",
        "knowledge_article_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- association + links ---
    op.create_table(
        "knowledge_article_tags",
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["knowledge_articles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["knowledge_tags.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("article_id", "tag_id", name="pk_knowledge_article_tags"),
    )
    op.create_index(
        op.f("ix_knowledge_article_tags_article_id"),
        "knowledge_article_tags",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_tags_tag_id"),
        "knowledge_article_tags",
        ["tag_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_article_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
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
            "target_type IN ('program', 'step')",
            name="ck_knowledge_article_links_target_type",
        ),
        sa.ForeignKeyConstraint(["article_id"], ["knowledge_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id",
            "target_type",
            "target_id",
            name="uq_knowledge_article_links_article_target",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_article_links_company_id"),
        "knowledge_article_links",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_links_article_id"),
        "knowledge_article_links",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_article_links_company_id_target",
        "knowledge_article_links",
        ["company_id", "target_type", "target_id"],
        unique=False,
    )

    # --- data backfill from legacy columns ---
    op.execute(
        """
        UPDATE knowledge_articles
        SET status = CASE WHEN is_published THEN 'published' ELSE 'draft' END,
            visibility = 'company'
        """
    )

    op.execute(
        """
        INSERT INTO knowledge_article_versions (
            id,
            article_id,
            version,
            title,
            body,
            body_format,
            change_summary,
            created_by_id,
            published_at,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            ka.id,
            1,
            ka.title,
            ka.body,
            'markdown',
            'Migrated from legacy knowledge_articles',
            ka.created_by_id,
            CASE WHEN ka.is_published THEN ka.updated_at ELSE NULL END,
            ka.created_at,
            ka.updated_at
        FROM knowledge_articles ka
        """
    )

    op.execute(
        """
        UPDATE knowledge_articles ka
        SET current_version_id = kav.id
        FROM knowledge_article_versions kav
        WHERE kav.article_id = ka.id
          AND kav.version = 1
        """
    )

    op.execute(
        """
        INSERT INTO knowledge_tags (id, company_id, name, slug, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            company_id,
            tag_name,
            left(
                CASE
                    WHEN regexp_replace(lower(trim(tag_name)), '[^a-z0-9]+', '-', 'g') IN ('', '-')
                    THEN 'tag'
                    ELSE trim(
                        both '-' from
                        regexp_replace(lower(trim(tag_name)), '[^a-z0-9]+', '-', 'g')
                    )
                END
                || '-' || substr(md5(tag_name), 1, 8),
                128
            ),
            now(),
            now()
        FROM (
            SELECT DISTINCT ka.company_id, trim(tag_name) AS tag_name
            FROM knowledge_articles ka
            CROSS JOIN LATERAL unnest(ka.tags) AS tag_name
            WHERE trim(tag_name) <> ''
        ) src
        """
    )

    op.execute(
        """
        INSERT INTO knowledge_article_tags (article_id, tag_id)
        SELECT DISTINCT ka.id, kt.id
        FROM knowledge_articles ka
        CROSS JOIN LATERAL unnest(ka.tags) AS tag_name
        JOIN knowledge_tags kt
          ON kt.company_id = ka.company_id
         AND kt.name = trim(tag_name)
        WHERE trim(tag_name) <> ''
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO knowledge_article_links (
            id, company_id, article_id, target_type, target_id, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            ka.company_id,
            ka.id,
            'program',
            ka.program_id,
            now(),
            now()
        FROM knowledge_articles ka
        WHERE ka.program_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO knowledge_article_links (
            id, company_id, article_id, target_type, target_id, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            ka.company_id,
            ka.id,
            'step',
            ka.step_id,
            now(),
            now()
        FROM knowledge_articles ka
        WHERE ka.step_id IS NOT NULL
        """
    )

    # --- drop legacy columns / indexes ---
    op.drop_index("ix_knowledge_articles_tags", table_name="knowledge_articles", postgresql_using="gin")
    op.drop_index(
        "ix_knowledge_articles_step_id",
        table_name="knowledge_articles",
        postgresql_where=sa.text("step_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_knowledge_articles_program_id",
        table_name="knowledge_articles",
        postgresql_where=sa.text("program_id IS NOT NULL"),
    )
    op.drop_index("ix_knowledge_articles_company_id_is_published", table_name="knowledge_articles")

    op.drop_constraint(
        "knowledge_articles_program_id_fkey",
        "knowledge_articles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "knowledge_articles_step_id_fkey",
        "knowledge_articles",
        type_="foreignkey",
    )

    op.drop_column("knowledge_articles", "title")
    op.drop_column("knowledge_articles", "body")
    op.drop_column("knowledge_articles", "tags")
    op.drop_column("knowledge_articles", "is_published")
    op.drop_column("knowledge_articles", "program_id")
    op.drop_column("knowledge_articles", "step_id")

    op.alter_column("knowledge_articles", "status", server_default=None)
    op.alter_column("knowledge_articles", "visibility", server_default=None)
    op.alter_column("knowledge_categories", "position", server_default=None)
    op.alter_column("knowledge_article_versions", "body_format", server_default=None)


def downgrade() -> None:
    # Recreate legacy columns
    op.add_column(
        "knowledge_articles",
        sa.Column("title", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("body", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("program_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("step_id", sa.UUID(), nullable=True),
    )

    op.execute(
        """
        UPDATE knowledge_articles ka
        SET
            title = coalesce(kav.title, 'Untitled'),
            body = coalesce(kav.body, ''),
            is_published = (ka.status = 'published')
        FROM knowledge_article_versions kav
        WHERE kav.id = ka.current_version_id
        """
    )
    op.execute(
        """
        UPDATE knowledge_articles
        SET title = coalesce(title, 'Untitled'),
            body = coalesce(body, '')
        WHERE title IS NULL OR body IS NULL
        """
    )
    op.execute(
        """
        UPDATE knowledge_articles ka
        SET program_id = kal.target_id
        FROM knowledge_article_links kal
        WHERE kal.article_id = ka.id
          AND kal.target_type = 'program'
        """
    )
    op.execute(
        """
        UPDATE knowledge_articles ka
        SET step_id = kal.target_id
        FROM knowledge_article_links kal
        WHERE kal.article_id = ka.id
          AND kal.target_type = 'step'
        """
    )
    op.execute(
        """
        UPDATE knowledge_articles ka
        SET tags = coalesce((
            SELECT array_agg(DISTINCT kt.name ORDER BY kt.name)
            FROM knowledge_article_tags kat
            JOIN knowledge_tags kt ON kt.id = kat.tag_id
            WHERE kat.article_id = ka.id
        ), '{}'::text[])
        """
    )

    op.alter_column("knowledge_articles", "title", nullable=False)
    op.alter_column("knowledge_articles", "body", nullable=False)
    op.alter_column("knowledge_articles", "tags", server_default=None)
    op.alter_column("knowledge_articles", "is_published", server_default=None)

    op.create_foreign_key(
        "knowledge_articles_program_id_fkey",
        "knowledge_articles",
        "onboarding_programs",
        ["program_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "knowledge_articles_step_id_fkey",
        "knowledge_articles",
        "steps",
        ["step_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_knowledge_articles_company_id_is_published",
        "knowledge_articles",
        ["company_id", "is_published"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_articles_program_id",
        "knowledge_articles",
        ["program_id"],
        unique=False,
        postgresql_where=sa.text("program_id IS NOT NULL"),
    )
    op.create_index(
        "ix_knowledge_articles_step_id",
        "knowledge_articles",
        ["step_id"],
        unique=False,
        postgresql_where=sa.text("step_id IS NOT NULL"),
    )
    op.create_index(
        "ix_knowledge_articles_tags",
        "knowledge_articles",
        ["tags"],
        unique=False,
        postgresql_using="gin",
    )

    op.drop_constraint(
        "fk_knowledge_articles_current_version_id",
        "knowledge_articles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_knowledge_articles_category_id",
        "knowledge_articles",
        type_="foreignkey",
    )
    op.drop_constraint("ck_knowledge_articles_status", "knowledge_articles", type_="check")
    op.drop_constraint("ck_knowledge_articles_visibility", "knowledge_articles", type_="check")
    op.drop_index("ix_knowledge_articles_category_id", table_name="knowledge_articles")
    op.drop_index("ix_knowledge_articles_company_id_status", table_name="knowledge_articles")
    op.drop_column("knowledge_articles", "current_version_id")
    op.drop_column("knowledge_articles", "category_id")
    op.drop_column("knowledge_articles", "status")
    op.drop_column("knowledge_articles", "visibility")

    op.drop_index(
        "ix_knowledge_article_links_company_id_target",
        table_name="knowledge_article_links",
    )
    op.drop_index(
        op.f("ix_knowledge_article_links_article_id"),
        table_name="knowledge_article_links",
    )
    op.drop_index(
        op.f("ix_knowledge_article_links_company_id"),
        table_name="knowledge_article_links",
    )
    op.drop_table("knowledge_article_links")

    op.drop_index(
        op.f("ix_knowledge_article_tags_tag_id"),
        table_name="knowledge_article_tags",
    )
    op.drop_index(
        op.f("ix_knowledge_article_tags_article_id"),
        table_name="knowledge_article_tags",
    )
    op.drop_table("knowledge_article_tags")

    op.drop_index(
        "ix_knowledge_article_versions_article_id_version",
        table_name="knowledge_article_versions",
    )
    op.drop_index(
        op.f("ix_knowledge_article_versions_created_by_id"),
        table_name="knowledge_article_versions",
    )
    op.drop_index(
        op.f("ix_knowledge_article_versions_article_id"),
        table_name="knowledge_article_versions",
    )
    op.drop_table("knowledge_article_versions")

    op.drop_index(op.f("ix_knowledge_tags_company_id"), table_name="knowledge_tags")
    op.drop_table("knowledge_tags")

    op.drop_index(
        "ix_knowledge_categories_company_id_parent_id",
        table_name="knowledge_categories",
    )
    op.drop_index(
        op.f("ix_knowledge_categories_parent_id"),
        table_name="knowledge_categories",
    )
    op.drop_index(
        op.f("ix_knowledge_categories_company_id"),
        table_name="knowledge_categories",
    )
    op.drop_table("knowledge_categories")
