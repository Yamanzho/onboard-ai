"""Phase 9B: departments, question topics, topic responsibilities, employee org fields.

Revision ID: a9b0c1d2e3f4
Revises: e3f4a5b6c7d8
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("departments", "question_topics", "topic_responsibilities")


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
    op.create_table(
        "departments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            name="uq_departments_company_id_slug",
        ),
    )
    op.create_index(
        op.f("ix_departments_company_id"),
        "departments",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_departments_company_id_is_active",
        "departments",
        ["company_id", "is_active"],
        unique=False,
    )

    op.create_table(
        "question_topics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            name="uq_question_topics_company_id_slug",
        ),
    )
    op.create_index(
        op.f("ix_question_topics_company_id"),
        "question_topics",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_question_topics_company_id_is_active",
        "question_topics",
        ["company_id", "is_active"],
        unique=False,
    )

    op.add_column(
        "employees",
        sa.Column("department_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("manager_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("job_title", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_employees_department_id",
        "employees",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_employees_manager_id",
        "employees",
        "employees",
        ["manager_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_employees_department_id",
        "employees",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        "ix_employees_manager_id",
        "employees",
        ["manager_id"],
        unique=False,
    )

    op.create_table(
        "topic_responsibilities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("topic_id", sa.UUID(), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("employee_id", sa.UUID(), nullable=True),
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
            "department_id IS NOT NULL OR employee_id IS NOT NULL",
            name="ck_topic_responsibilities_target_present",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["question_topics.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("topic_id", name="uq_topic_responsibilities_topic_id"),
    )
    op.create_index(
        op.f("ix_topic_responsibilities_company_id"),
        "topic_responsibilities",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_topic_responsibilities_topic_id"),
        "topic_responsibilities",
        ["topic_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_topic_responsibilities_department_id"),
        "topic_responsibilities",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_topic_responsibilities_employee_id"),
        "topic_responsibilities",
        ["employee_id"],
        unique=False,
    )

    for table in _TABLES:
        _protect_table(table)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.drop_table("topic_responsibilities")
    op.drop_index("ix_employees_manager_id", table_name="employees")
    op.drop_index("ix_employees_department_id", table_name="employees")
    op.drop_constraint("fk_employees_manager_id", "employees", type_="foreignkey")
    op.drop_constraint("fk_employees_department_id", "employees", type_="foreignkey")
    op.drop_column("employees", "job_title")
    op.drop_column("employees", "manager_id")
    op.drop_column("employees", "department_id")
    op.drop_index(
        "ix_question_topics_company_id_is_active",
        table_name="question_topics",
    )
    op.drop_index(op.f("ix_question_topics_company_id"), table_name="question_topics")
    op.drop_table("question_topics")
    op.drop_index("ix_departments_company_id_is_active", table_name="departments")
    op.drop_index(op.f("ix_departments_company_id"), table_name="departments")
    op.drop_table("departments")
