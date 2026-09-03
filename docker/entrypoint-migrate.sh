#!/bin/sh
set -eu

echo "[migrate] waiting for database…"
python - <<'PY'
import asyncio
import os
import sys

import asyncpg


async def wait() -> None:
    url = os.environ.get("BOOTSTRAP_DATABASE_URL") or os.environ.get(
        "MIGRATION_DATABASE_URL"
    ) or os.environ["DATABASE_URL"]
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    candidates = [url]
    pg_user = os.environ.get("POSTGRES_USER")
    pg_pass = os.environ.get("POSTGRES_PASSWORD")
    pg_db = os.environ.get("POSTGRES_DB", "onboard_ai")
    if pg_user and pg_pass:
        candidates.append(
            f"postgresql://{pg_user}:{pg_pass}@db:5432/{pg_db}"
        )
    last_exc: Exception | None = None
    for attempt in range(60):
        for candidate in candidates:
            try:
                conn = await asyncpg.connect(candidate)
                await conn.close()
                print("[migrate] database is ready")
                return
            except Exception as exc:  # noqa: BLE001 — retry until ready
                last_exc = exc
        print(f"[migrate] db not ready ({attempt + 1}/60): {last_exc}")
        await asyncio.sleep(1)
    sys.exit(1)


asyncio.run(wait())
PY

echo "[migrate] bootstrapping SEC-R3 database roles…"
python -m scripts.bootstrap_rls_roles

echo "[migrate] running migrations…"
export MIGRATION_DATABASE_URL="${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL is required}"
alembic upgrade head
echo "[migrate] complete"
