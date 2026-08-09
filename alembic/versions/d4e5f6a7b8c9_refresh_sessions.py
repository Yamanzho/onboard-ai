"""refresh sessions for rotatable opaque refresh tokens

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-07 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refresh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_sessions_token_hash", "refresh_sessions", ["token_hash"])
    op.create_index("ix_refresh_sessions_family_id", "refresh_sessions", ["family_id"])
    op.create_index("ix_refresh_sessions_subject_type", "refresh_sessions", ["subject_type"])
    op.create_index("ix_refresh_sessions_subject_id", "refresh_sessions", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_sessions_subject_id", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_subject_type", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_family_id", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_token_hash", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
