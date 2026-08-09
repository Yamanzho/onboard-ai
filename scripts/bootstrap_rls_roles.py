#!/usr/bin/env python3
"""Idempotent SEC-R3 role bootstrap (onboard_owner / onboard_app).

Must run as a PostgreSQL superuser (typically POSTGRES_USER=onboard) before
Alembic connects as onboard_owner. Safe to re-run.

    python -m scripts.bootstrap_rls_roles
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import asyncpg  # noqa: E402

from app.core.config import get_settings  # noqa: E402

_APP_TABLES = (
    "alembic_version",
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


def _bootstrap_url() -> str:
    """Prefer explicit bootstrap URL; else POSTGRES_* credentials."""
    explicit = os.environ.get("BOOTSTRAP_DATABASE_URL", "").strip()
    if explicit:
        return explicit.replace("postgresql+asyncpg://", "postgresql://", 1)

    user = os.environ.get("POSTGRES_USER", "onboard")
    password = os.environ.get("POSTGRES_PASSWORD", "onboard")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "onboard_ai")

    # Host-local pytest often uses localhost; Compose api uses host `db`.
    settings = get_settings()
    parsed = urlparse(settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.hostname in {"localhost", "127.0.0.1", "db"}:
        host = parsed.hostname or host
        port = str(parsed.port or port)
        db = (parsed.path or f"/{db}").lstrip("/") or db

    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@"
        f"{host}:{port}/{db}"
    )


async def bootstrap() -> None:
    settings = get_settings()
    owner_pw = os.environ.get("ONBOARD_OWNER_PASSWORD", settings.onboard_owner_password)
    app_pw = os.environ.get("ONBOARD_APP_PASSWORD", settings.onboard_app_password)

    url = _bootstrap_url()
    conn = await asyncpg.connect(url)
    try:
        owner_exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = 'onboard_owner'"
        )
        owner_lit = await conn.fetchval("SELECT quote_literal($1)", owner_pw)
        app_lit = await conn.fetchval("SELECT quote_literal($1)", app_pw)
        if not owner_exists:
            await conn.execute(
                f"CREATE ROLE onboard_owner LOGIN PASSWORD {owner_lit} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE"
            )
        else:
            await conn.execute(
                f"ALTER ROLE onboard_owner WITH LOGIN PASSWORD {owner_lit} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE"
            )

        app_exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = 'onboard_app'"
        )
        if not app_exists:
            await conn.execute(
                f"CREATE ROLE onboard_app LOGIN PASSWORD {app_lit} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
            )
        else:
            await conn.execute(
                f"ALTER ROLE onboard_app WITH LOGIN PASSWORD {app_lit} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
            )

        await conn.execute("ALTER ROLE onboard_owner BYPASSRLS")
        await conn.execute("ALTER ROLE onboard_app NOBYPASSRLS")

        dbname = (urlparse(url).path or "/onboard_ai").lstrip("/") or "onboard_ai"
        await conn.execute(f'GRANT CONNECT ON DATABASE "{dbname}" TO onboard_owner')
        await conn.execute(f'GRANT CONNECT ON DATABASE "{dbname}" TO onboard_app')
        await conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO onboard_owner")
        await conn.execute("GRANT USAGE ON SCHEMA public TO onboard_app")
        await conn.execute("GRANT ALL ON SCHEMA public TO onboard_owner")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS app")
        await conn.execute("ALTER SCHEMA app OWNER TO onboard_owner")
        await conn.execute("GRANT USAGE ON SCHEMA app TO onboard_app")
        await conn.execute("GRANT USAGE ON SCHEMA app TO PUBLIC")

        for table in _APP_TABLES:
            exists = await conn.fetchval("SELECT to_regclass($1)", f"public.{table}")
            if exists is None:
                continue
            await conn.execute(f'ALTER TABLE "{table}" OWNER TO onboard_owner')
            await conn.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO onboard_app'
            )

        await conn.execute(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO onboard_app"
        )
        await conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE onboard_owner IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO onboard_app"
        )
        await conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE onboard_owner IN SCHEMA public "
            "GRANT USAGE, SELECT ON SEQUENCES TO onboard_app"
        )
        print("SEC-R3 roles ready: onboard_owner (BYPASSRLS), onboard_app (NOBYPASSRLS)")
    finally:
        await conn.close()


def main() -> None:
    asyncio.run(bootstrap())


if __name__ == "__main__":
    main()
