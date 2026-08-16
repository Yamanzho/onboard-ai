"""AI-11A: employee-owned conversation persistence foundation.

Revision ID: e2f3a4b5c6d7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-16

Evolves the unused ``ai_conversations`` placeholder (JSONB messages,
required telegram_chat_id) into a relational conversation + message
model. Conversation storage is DATA, not KB authorization.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONVERSATIONS = "ai_conversations"
_MESSAGES = "ai_messages"
_MAX_MESSAGE_CHARS = 16_000


def _grant_app_table(table: str) -> None:
    conn = op.get_bind()
    owner_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_owner'")
    ).scalar()
    app_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'onboard_app'")
    ).scalar()
    if owner_exists:
        op.execute(f'ALTER TABLE "{table}" OWNER TO onboard_owner')
    if app_exists:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO onboard_app'
        )


def upgrade() -> None:
    op.add_column(_CONVERSATIONS, sa.Column("title", sa.Text(), nullable=True))
    op.execute(
        f"ALTER TABLE {_CONVERSATIONS} DROP CONSTRAINT IF EXISTS ck_ai_conversations_status"
    )
    op.execute(
        f"UPDATE {_CONVERSATIONS} SET status = 'archived' WHERE status = 'closed'"
    )
    op.create_check_constraint(
        "ck_ai_conversations_status",
        _CONVERSATIONS,
        "status IN ('active', 'archived')",
    )

    op.create_table(
        _MESSAGES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
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
            "role IN ('user', 'assistant')",
            name="ck_ai_messages_role",
        ),
        sa.CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_ai_messages_content_not_blank",
        ),
        sa.CheckConstraint(
            f"char_length(content) <= {_MAX_MESSAGE_CHARS}",
            name="ck_ai_messages_content_max_length",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{_CONVERSATIONS}.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_messages_company_id",
        _MESSAGES,
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_messages_conversation_id_created_at",
        _MESSAGES,
        ["conversation_id", "created_at"],
        unique=False,
    )

    op.execute(
        f"""
        INSERT INTO {_MESSAGES}
            (id, conversation_id, company_id, role, content, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            c.id,
            c.company_id,
            CASE
                WHEN elem->>'role' IN ('user', 'assistant') THEN elem->>'role'
                ELSE 'user'
            END,
            btrim(COALESCE(elem->>'content', elem->>'text', '')),
            c.created_at,
            c.updated_at
        FROM {_CONVERSATIONS} AS c
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(c.messages, '[]'::jsonb)) AS elem
        WHERE char_length(btrim(COALESCE(elem->>'content', elem->>'text', ''))) > 0
        """
    )

    op.execute(f'ALTER TABLE "{_MESSAGES}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_MESSAGES}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{_MESSAGES}"')
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON "{_MESSAGES}"
        FOR ALL
        USING (app.is_platform() OR company_id = app.company_id())
        WITH CHECK (app.is_platform() OR company_id = app.company_id())
        """
    )
    _grant_app_table(_MESSAGES)

    op.drop_index(
        "ix_ai_conversations_telegram_chat_id_status",
        table_name=_CONVERSATIONS,
    )
    op.drop_index(
        "ix_ai_conversations_assignment_id",
        table_name=_CONVERSATIONS,
        postgresql_where=sa.text("assignment_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_ai_conversations_company_id_created_at",
        table_name=_CONVERSATIONS,
    )
    op.drop_index(
        "ix_ai_conversations_employee_id_status",
        table_name=_CONVERSATIONS,
    )
    op.execute(
        f"ALTER TABLE {_CONVERSATIONS} DROP CONSTRAINT IF EXISTS "
        "ai_conversations_assignment_id_fkey"
    )
    op.drop_column(_CONVERSATIONS, "telegram_chat_id")
    op.drop_column(_CONVERSATIONS, "assignment_id")
    op.drop_column(_CONVERSATIONS, "messages")
    op.drop_column(_CONVERSATIONS, "meta")
    op.drop_column(_CONVERSATIONS, "closed_at")
    op.create_index(
        "ix_ai_conversations_company_id_employee_id_updated_at",
        _CONVERSATIONS,
        ["company_id", "employee_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_conversations_company_id_employee_id_updated_at",
        table_name=_CONVERSATIONS,
    )
    op.add_column(
        _CONVERSATIONS,
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        _CONVERSATIONS,
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        _CONVERSATIONS,
        sa.Column(
            "messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        _CONVERSATIONS,
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        _CONVERSATIONS,
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "ai_conversations_assignment_id_fkey",
        _CONVERSATIONS,
        "assignments",
        ["assignment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        f"""
        UPDATE {_CONVERSATIONS} AS c
        SET messages = COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object('role', m.role, 'text', m.content)
                ORDER BY m.created_at ASC, m.id ASC
            )
            FROM {_MESSAGES} AS m
            WHERE m.conversation_id = c.id
        ), '[]'::jsonb)
        """
    )
    op.execute(f"UPDATE {_CONVERSATIONS} SET telegram_chat_id = 0 WHERE telegram_chat_id IS NULL")
    op.execute(f"UPDATE {_CONVERSATIONS} SET messages = '[]'::jsonb WHERE messages IS NULL")
    op.execute(f"UPDATE {_CONVERSATIONS} SET meta = '{{}}'::jsonb WHERE meta IS NULL")
    op.alter_column(_CONVERSATIONS, "telegram_chat_id", nullable=False)
    op.alter_column(_CONVERSATIONS, "messages", nullable=False)
    op.alter_column(_CONVERSATIONS, "meta", nullable=False)

    op.create_index(
        "ix_ai_conversations_telegram_chat_id_status",
        _CONVERSATIONS,
        ["telegram_chat_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_ai_conversations_assignment_id",
        _CONVERSATIONS,
        ["assignment_id"],
        unique=False,
        postgresql_where=sa.text("assignment_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ai_conversations_company_id_created_at",
        _CONVERSATIONS,
        ["company_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_conversations_employee_id_status",
        _CONVERSATIONS,
        ["employee_id", "status"],
        unique=False,
    )

    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{_MESSAGES}"')
    op.drop_index("ix_ai_messages_conversation_id_created_at", table_name=_MESSAGES)
    op.drop_index("ix_ai_messages_company_id", table_name=_MESSAGES)
    op.drop_table(_MESSAGES)

    op.execute(
        f"ALTER TABLE {_CONVERSATIONS} DROP CONSTRAINT IF EXISTS ck_ai_conversations_status"
    )
    op.execute(
        f"UPDATE {_CONVERSATIONS} SET status = 'closed' WHERE status = 'archived'"
    )
    op.create_check_constraint(
        "ck_ai_conversations_status",
        _CONVERSATIONS,
        "status IN ('active', 'closed')",
    )
    op.drop_column(_CONVERSATIONS, "title")
