#!/bin/sh
# Host-operated production deploy helper. Does not touch a remote host by itself.
# Run from the repository root on the VPS after reviewing the runbook.
set -eu

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml"
READY_URL="${ONBOARDAI_READY_URL:-http://127.0.0.1:3000/ready}"
HEALTH_URL="${ONBOARDAI_HEALTH_URL:-http://127.0.0.1:3000/health}"
FRONTEND_URL="${ONBOARDAI_FRONTEND_URL:-http://127.0.0.1:3000/}"
AUTH_URL="${ONBOARDAI_AUTH_URL:-http://127.0.0.1:3000/api/v1/auth/login}"
WAIT_SECONDS="${ONBOARDAI_READY_WAIT_SECONDS:-90}"

_die() {
  echo "[deploy] ERROR: $1" >&2
  exit 1
}

_info() {
  echo "[deploy] $1"
}

[ -f docker-compose.yml ] || _die "run this script from the repository root"
[ -f docker-compose.prod.yml ] || _die "missing docker-compose.prod.yml"
[ -f .env ] || _die "missing .env"

_info "preflight: compose configuration"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES config --quiet

_info "preflight: recent backup marker (advisory)"
MARKER="${BACKUP_STATUS_FILE:-/var/lib/onboard-ai-backup/last-backup.json}"
if [ -f "$MARKER" ]; then
  _info "backup marker present at $MARKER"
else
  _info "backup marker not found; continue only if a recent backup is confirmed"
fi

if [ "${ONBOARDAI_SKIP_BUILD:-0}" != "1" ]; then
  _info "build images"
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES build api bot frontend migrate
fi

_info "run migrations exactly once"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES run --rm migrate

_info "restart API (single instance; brief downtime expected)"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d --no-deps --force-recreate api

_info "wait for readiness at $READY_URL"
attempt=1
while [ "$attempt" -le "$WAIT_SECONDS" ]; do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && curl -fsS "$READY_URL" >/dev/null 2>&1; then
    _info "API is live and ready"
    break
  fi
  if [ "$attempt" -eq "$WAIT_SECONDS" ]; then
    _die "API did not become ready within ${WAIT_SECONDS}s; inspect logs and do not declare success"
  fi
  attempt=$((attempt + 1))
  sleep 1
done

_info "restart bot if present"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d --no-deps --force-recreate bot

_info "verify frontend"
curl -fsS "$FRONTEND_URL" >/dev/null || _die "frontend root did not respond"
curl -fsS -o /dev/null -w "%{http_code}" -X POST "$AUTH_URL" \
  -H "content-type: application/json" \
  -d '{}' | grep -Eq '^(400|401|403|422)$' \
  || _die "auth endpoint did not return a basic client error"

# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T api alembic current >/dev/null \
  || _die "could not read alembic current from API"

_info "smoke checks passed"
_info "If readiness later fails, revert the image only when the last migration is backward compatible."
_info "This script does not roll back automatically."
