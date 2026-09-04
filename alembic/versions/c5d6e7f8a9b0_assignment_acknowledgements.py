"""Phase 9H: acknowledgement assignments and frozen KnowledgeArticleVersion items.

Revision ID: c5d6e7f8a9b0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASSIGNMENTS = "assignments"
_ITEMS = "assignment_acknowledgement_items"
_VERSIONS = "knowledge_article_versions"


def _protect_table(table: str) -> None:
    conn = op.get_bind()
    owner_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_owner'")
    ).scalar()
    app_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_app'")
    ).scalar()
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON "{table}"
        FOR ALL
        USING (app.is_platform() OR company_id = app.company_id())
        WITH CHECK (app.is_platform() OR company_id = app.company_id())
        """
    )
    if owner_exists:
        op.execute(f'ALTER TABLE "{table}" OWNER TO onboard_owner')
    if app_exists:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO onboard_app'
        )


def upgrade() -> None:
    op.add_column(
        _ASSIGNMENTS,
        sa.Column(
            "assignment_type",
            sa.String(length=32),
            nullable=False,
            server_default="program",
        ),
    )
    op.create_check_constraint(
        "ck_assignments_assignment_type",
        _ASSIGNMENTS,
        "assignment_type IN ('program', 'acknowledgement')",
    )
    op.drop_index(
        "uq_assignments_employee_program_active",
        table_name=_ASSIGNMENTS,
    )
    op.alter_column(
        _ASSIGNMENTS,
        "program_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_assignments_type_program_id",
        _ASSIGNMENTS,
        "(assignment_type = 'program' AND program_id IS NOT NULL) OR "
        "(assignment_type = 'acknowledgement' AND program_id IS NULL)",
    )
    op.create_index(
        "uq_assignments_employee_program_active",
        _ASSIGNMENTS,
        ["employee_id", "program_id"],
        unique=True,
        postgresql_where=sa.text(
            "assignment_type = 'program' AND status IN ('pending', 'in_progress')"
        ),
    )
    op.create_index(
        "ix_assignments_assignment_type",
        _ASSIGNMENTS,
        ["assignment_type"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_assignments_id_assignment_type",
        _ASSIGNMENTS,
        ["id", "assignment_type"],
    )

    op.create_index(
        "uq_knowledge_article_versions_id_article_id",
        _VERSIONS,
        ["article_id", "id"],
        unique=True,
    )

    op.create_table(
        _ITEMS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column(
            "assignment_type",
            sa.String(length=32),
            nullable=False,
            server_default="acknowledgement",
        ),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("article_version_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "is_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
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
            "assignment_type = 'acknowledgement'",
            name="ck_ack_items_assignment_type",
        ),
        sa.CheckConstraint("position >= 1", name="ck_ack_items_position_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assignment_id", "assignment_type"],
            ["assignments.id", "assignments.assignment_type"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["knowledge_articles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["article_version_id"],
            ["knowledge_article_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["article_id", "article_version_id"],
            ["knowledge_article_versions.article_id", "knowledge_article_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assignment_id",
            "position",
            name="uq_ack_items_assignment_id_position",
        ),
        sa.UniqueConstraint(
            "assignment_id",
            "article_id",
            name="uq_ack_items_assignment_id_article_id",
        ),
        sa.UniqueConstraint(
            "assignment_id",
            "article_version_id",
            name="uq_ack_items_assignment_id_article_version_id",
        ),
    )
    op.create_index(
        "ix_assignment_acknowledgement_items_company_id",
        _ITEMS,
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_assignment_acknowledgement_items_assignment_id",
        _ITEMS,
        ["assignment_id"],
        unique=False,
    )
    op.create_index(
        "ix_assignment_acknowledgement_items_article_id",
        _ITEMS,
        ["article_id"],
        unique=False,
    )
    op.create_index(
        "ix_assignment_acknowledgement_items_article_version_id",
        _ITEMS,
        ["article_version_id"],
        unique=False,
    )
    _protect_table(_ITEMS)


def downgrade() -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{_ITEMS}"')
    op.drop_index(
        "ix_assignment_acknowledgement_items_article_version_id",
        table_name=_ITEMS,
    )
    op.drop_index(
        "ix_assignment_acknowledgement_items_article_id",
        table_name=_ITEMS,
    )
    op.drop_index(
        "ix_assignment_acknowledgement_items_assignment_id",
        table_name=_ITEMS,
    )
    op.drop_index(
        "ix_assignment_acknowledgement_items_company_id",
        table_name=_ITEMS,
    )
    op.drop_table(_ITEMS)
    op.drop_index(
        "uq_knowledge_article_versions_id_article_id",
        table_name=_VERSIONS,
    )
    op.drop_constraint(
        "uq_assignments_id_assignment_type",
        _ASSIGNMENTS,
        type_="unique",
    )
    op.drop_index("ix_assignments_assignment_type", table_name=_ASSIGNMENTS)
    op.drop_index(
        "uq_assignments_employee_program_active",
        table_name=_ASSIGNMENTS,
    )
    op.drop_constraint("ck_assignments_type_program_id", _ASSIGNMENTS, type_="check")
    op.alter_column(
        _ASSIGNMENTS,
        "program_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_index(
        "uq_assignments_employee_program_active",
        _ASSIGNMENTS,
        ["employee_id", "program_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'in_progress')"),
    )
    op.drop_constraint("ck_assignments_assignment_type", _ASSIGNMENTS, type_="check")
    op.drop_column(_ASSIGNMENTS, "assignment_type")
