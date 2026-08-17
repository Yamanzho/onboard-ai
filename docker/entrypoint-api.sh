#!/bin/sh
set -eu

APP_ENV_VALUE="${APP_ENV:-development}"
if [ "$APP_ENV_VALUE" = "production" ] && [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "[api] SEED_DEMO=true is forbidden when APP_ENV=production" >&2
  exit 1
fi

echo "[api] waiting for database…"
python - <<'PY'
import asyncio
import os
import sys

import asyncpg


async def wait() -> None:
    # Prefer bootstrap/superuser URL for readiness (roles may not exist yet).
    url = os.environ.get("BOOTSTRAP_DATABASE_URL") or os.environ.get(
        "MIGRATION_DATABASE_URL"
    ) or os.environ["DATABASE_URL"]
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    # Fall back to POSTGRES_* if app role is not ready yet.
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
                print("[api] database is ready")
                return
            except Exception as exc:  # noqa: BLE001 — retry until ready
                last_exc = exc
        print(f"[api] db not ready ({attempt + 1}/60): {last_exc}")
        await asyncio.sleep(1)
    sys.exit(1)


asyncio.run(wait())
PY

echo "[api] bootstrapping SEC-R3 database roles…"
python -m scripts.bootstrap_rls_roles

echo "[api] running migrations…"
# Alembic uses MIGRATION_DATABASE_URL (onboard_owner) via alembic/env.py.
export MIGRATION_DATABASE_URL="${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL is required}"
alembic upgrade head

# Demo seed is opt-in (never default-on for production-like deploys).
if [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "[api] seeding demo tenant…"
  python -m scripts.seed_demo
fi

echo "[api] seeding platform Super Admin…"
python -m scripts.seed_super_admin

echo "[api] starting uvicorn (APP_ENV=${APP_ENV_VALUE})…"
if [ "${APP_ENV_VALUE}" = "production" ]; then
  # --forwarded-allow-ips='*' is safe only because docker-compose.prod.yml
  # publishes no API host port. Do not combine with a public :8000 bind.
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --workers "${UVICORN_WORKERS:-2}" \
    --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
