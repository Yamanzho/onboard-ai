#!/bin/sh
set -eu

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "[bot] BOT_TOKEN empty — bot idle (set BOT_TOKEN in .env and restart to enable Telegram)."
  echo "[bot] BOT_COMPANY_ID=${BOT_COMPANY_ID:-unset} (optional; not used for identity lookup)"
  exec sleep infinity
fi

if [ -z "${BOT_SERVICE_TOKEN:-}" ]; then
  echo "[bot] BOT_SERVICE_TOKEN is required"
  exit 1
fi

echo "[bot] waiting for API…"
python - <<'PY'
import os
import sys
import time
import urllib.error
import urllib.request

base = os.environ.get("API_BASE_URL", "http://api:8000").rstrip("/")
url = f"{base}/health"
for attempt in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status == 200:
                print("[bot] API is ready")
                sys.exit(0)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[bot] API not ready ({attempt + 1}/60): {exc}")
        time.sleep(1)
sys.exit(1)
PY

echo "[bot] starting Telegram bot…"
exec python -m app.bot
