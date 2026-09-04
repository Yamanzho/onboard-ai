"""Alembic environment configuration."""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (  # noqa: F401 — register models on Base.metadata
    AIConversation,
    AIMessage,
    Assignment,
    AssignmentAcknowledgementItem,
    Company,
    CompanyAuditLog,
    CompanySubscription,
    Department,
    Employee,
    EmployeeInvite,
    KnowledgeArticle,
    KnowledgeArticleChunk,
    KnowledgeArticleLink,
    KnowledgeArticleTag,
    KnowledgeArticleVersion,
    KnowledgeCategory,
    KnowledgeTag,
    OnboardingProgram,
    PlatformAuditLog,
    Progress,
    QuestionTopic,
    RefreshSession,
    Step,
    SubscriptionHistoryEvent,
    SuperAdmin,
    TopicResponsibility,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Sync URL for Alembic (asyncpg -> psycopg).

    Prefer MIGRATION_DATABASE_URL (onboard_owner). Fall back to DATABASE_URL
    only for local transition when the migrator URL is unset.
    """
    settings = get_settings()
    raw = (
        os.environ.get("MIGRATION_DATABASE_URL")
        or settings.migration_database_url
        or settings.database_url
    )
    return raw.replace("+asyncpg", "+psycopg")


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
