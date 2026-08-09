"""SEC-R3 M6: FORCE ROW LEVEL SECURITY on all protected tables.

Revision ID: f6a7b8c9d0e1
Revises: f4d5e6f7a8b9
Create Date: 2026-08-08
"""

from __future__ import annotations

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "f5e6f7a8b9c0"
branch_labels = None
depends_on = None

_TABLES = (
    "companies",
    "employees",
    "onboarding_programs",
    "steps",
    "assignments",
    "progress",
    "knowledge_categories",
    "knowledge_tags",
    "knowledge_articles",
    "knowledge_article_versions",
    "knowledge_article_tags",
    "knowledge_article_links",
    "ai_conversations",
    "company_subscriptions",
    "subscription_history_events",
    "employee_invites",
    "refresh_sessions",
    "super_admins",
    "platform_audit_logs",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
