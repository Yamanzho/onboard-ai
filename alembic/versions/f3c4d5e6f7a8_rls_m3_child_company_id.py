"""SEC-R3 M3: denormalize company_id onto child tables + backfill.

Revision ID: f3c4d5e6f7a8
Revises: f2b3c4d5e6f7
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f3c4d5e6f7a8"
down_revision = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- steps ---
    op.add_column(
        "steps",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE steps AS s
        SET company_id = p.company_id
        FROM onboarding_programs AS p
        WHERE s.program_id = p.id
        """
    )
    op.alter_column("steps", "company_id", nullable=False)
    op.create_foreign_key(
        "fk_steps_company_id_companies",
        "steps",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_steps_company_id", "steps", ["company_id"])

    # --- progress ---
    op.add_column(
        "progress",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE progress AS pr
        SET company_id = a.company_id
        FROM assignments AS a
        WHERE pr.assignment_id = a.id
        """
    )
    op.alter_column("progress", "company_id", nullable=False)
    op.create_foreign_key(
        "fk_progress_company_id_companies",
        "progress",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_progress_company_id", "progress", ["company_id"])

    # --- knowledge_article_versions ---
    op.add_column(
        "knowledge_article_versions",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE knowledge_article_versions AS v
        SET company_id = a.company_id
        FROM knowledge_articles AS a
        WHERE v.article_id = a.id
        """
    )
    op.alter_column("knowledge_article_versions", "company_id", nullable=False)
    op.create_foreign_key(
        "fk_knowledge_article_versions_company_id_companies",
        "knowledge_article_versions",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_knowledge_article_versions_company_id",
        "knowledge_article_versions",
        ["company_id"],
    )

    # --- knowledge_article_tags ---
    op.add_column(
        "knowledge_article_tags",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE knowledge_article_tags AS t
        SET company_id = a.company_id
        FROM knowledge_articles AS a
        WHERE t.article_id = a.id
        """
    )
    op.alter_column("knowledge_article_tags", "company_id", nullable=False)
    op.create_foreign_key(
        "fk_knowledge_article_tags_company_id_companies",
        "knowledge_article_tags",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_knowledge_article_tags_company_id",
        "knowledge_article_tags",
        ["company_id"],
    )
    # Keep secondary M2M inserts working: copy company_id from article.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.set_article_tag_company_id()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          SELECT company_id INTO NEW.company_id
          FROM knowledge_articles
          WHERE id = NEW.article_id;
          IF NEW.company_id IS NULL THEN
            RAISE EXCEPTION 'knowledge_article_tags: parent article % not found',
              NEW.article_id;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_knowledge_article_tags_company_id
        BEFORE INSERT OR UPDATE OF article_id
        ON knowledge_article_tags
        FOR EACH ROW
        EXECUTE FUNCTION app.set_article_tag_company_id()
        """
    )

    # --- employee_invites ---
    op.add_column(
        "employee_invites",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE employee_invites AS i
        SET company_id = e.company_id
        FROM employees AS e
        WHERE i.employee_id = e.id
        """
    )
    op.alter_column("employee_invites", "company_id", nullable=False)
    op.create_foreign_key(
        "fk_employee_invites_company_id_companies",
        "employee_invites",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_employee_invites_company_id", "employee_invites", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_employee_invites_company_id", table_name="employee_invites")
    op.drop_constraint(
        "fk_employee_invites_company_id_companies",
        "employee_invites",
        type_="foreignkey",
    )
    op.drop_column("employee_invites", "company_id")

    op.execute("DROP TRIGGER IF EXISTS trg_knowledge_article_tags_company_id ON knowledge_article_tags")
    op.execute("DROP FUNCTION IF EXISTS app.set_article_tag_company_id()")
    op.drop_index("ix_knowledge_article_tags_company_id", table_name="knowledge_article_tags")
    op.drop_constraint(
        "fk_knowledge_article_tags_company_id_companies",
        "knowledge_article_tags",
        type_="foreignkey",
    )
    op.drop_column("knowledge_article_tags", "company_id")

    op.drop_index(
        "ix_knowledge_article_versions_company_id",
        table_name="knowledge_article_versions",
    )
    op.drop_constraint(
        "fk_knowledge_article_versions_company_id_companies",
        "knowledge_article_versions",
        type_="foreignkey",
    )
    op.drop_column("knowledge_article_versions", "company_id")

    op.drop_index("ix_progress_company_id", table_name="progress")
    op.drop_constraint("fk_progress_company_id_companies", "progress", type_="foreignkey")
    op.drop_column("progress", "company_id")

    op.drop_index("ix_steps_company_id", table_name="steps")
    op.drop_constraint("fk_steps_company_id_companies", "steps", type_="foreignkey")
    op.drop_column("steps", "company_id")
