#!/bin/sh
set -eu

echo "[api] waiting for database…"
python - <<'PY'
import asyncio
import os
import sys

import asyncpg


async def wait() -> None:
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    for attempt in range(60):
        try:
            conn = await asyncpg.connect(url)
            await conn.close()
            print("[api] database is ready")
            return
        except Exception as exc:  # noqa: BLE001 — retry until ready
            print(f"[api] db not ready ({attempt + 1}/60): {exc}")
            await asyncio.sleep(1)
    sys.exit(1)


asyncio.run(wait())
PY

echo "[api] running migrations…"
alembic upgrade head

if [ "${SEED_DEMO:-true}" = "true" ]; then
  echo "[api] seeding demo tenant…"
  python -m scripts.seed_demo
fi

echo "[api] seeding platform Super Admin…"
python -m scripts.seed_super_admin

echo "[api] starting uvicorn…"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
