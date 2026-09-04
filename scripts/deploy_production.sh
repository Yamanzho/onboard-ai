#!/bin/sh
# Host-operated production deploy helper. Does not touch a remote host by itself.
# Run from the repository root on the VPS after reviewing the runbook.
set -eu

READY_URL="${ONBOARDAI_READY_URL:-http://127.0.0.1:3000/ready}"
HEALTH_URL="${ONBOARDAI_HEALTH_URL:-http://127.0.0.1:3000/health}"
FRONTEND_URL="${ONBOARDAI_FRONTEND_URL:-http://127.0.0.1:3000/}"
AUTH_URL="${ONBOARDAI_AUTH_URL:-http://127.0.0.1:3000/api/v1/auth/login}"
WAIT_SECONDS="${ONBOARDAI_READY_WAIT_SECONDS:-90}"
DB_CONTAINER="${ONBOARDAI_DB_CONTAINER:-onboard-ai-db}"
DB_MOUNT="${ONBOARDAI_DB_MOUNT:-/var/lib/postgresql/data}"

_die() {
  echo "[deploy] ERROR: $1" >&2
  exit 1
}

_info() {
  echo "[deploy] $1"
}

_compose() {
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES "$@"
}

_resolved_postgres_volume() {
  _compose config --format json | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
vol = (cfg.get("volumes") or {}).get("postgres_data") or {}
name = vol.get("name") or ""
external = vol.get("external")
if isinstance(external, dict):
    external_flag = True
    name = external.get("name") or name
else:
    external_flag = bool(external)
print(name)
print("external" if external_flag else "managed")
'
}

_live_postgres_volume() {
  docker inspect -f '{{range .Mounts}}{{if eq .Destination "'"$DB_MOUNT"'"}}{{.Name}}{{end}}{{end}}' \
    "$DB_CONTAINER" 2>/dev/null || true
}

[ -f docker-compose.yml ] || _die "run this script from the repository root"
[ -f docker-compose.prod.yml ] || _die "missing docker-compose.prod.yml"
[ -f .env ] || _die "missing .env"

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml"
COMPOSE_FILE_LIST="docker-compose.yml docker-compose.prod.yml"
if [ -f docker-compose.prod.local.yml ]; then
  COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.prod.local.yml"
  COMPOSE_FILE_LIST="$COMPOSE_FILE_LIST docker-compose.prod.local.yml"
fi

_info "preflight: compose files: $COMPOSE_FILE_LIST"
_compose config --quiet || _die "compose configuration is invalid"

vol_info="$(_resolved_postgres_volume)" || _die "could not resolve postgres_data volume"
resolved_volume=$(printf '%s\n' "$vol_info" | sed -n '1p')
volume_kind=$(printf '%s\n' "$vol_info" | sed -n '2p')
[ -n "$resolved_volume" ] || _die "resolved postgres volume name is empty"
[ "$volume_kind" = "external" ] || _die "postgres_data must be an external volume (refusing managed/created volume $resolved_volume)"

if ! docker volume inspect "$resolved_volume" >/dev/null 2>&1; then
  _die "resolved postgres volume $resolved_volume does not exist; refusing to create a replacement"
fi

required_volume="${ONBOARDAI_REQUIRED_POSTGRES_VOLUME:-}"
if [ -n "$required_volume" ] && [ "$resolved_volume" != "$required_volume" ]; then
  _die "resolved postgres volume $resolved_volume does not match required $required_volume"
fi

if docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
  live_volume="$(_live_postgres_volume)"
  [ -n "$live_volume" ] || _die "running $DB_CONTAINER has no $DB_MOUNT mount"
  if [ "$live_volume" != "$resolved_volume" ]; then
    _die "resolved postgres volume $resolved_volume does not match live $DB_CONTAINER volume $live_volume"
  fi
  _info "preflight: postgres volume $resolved_volume (external, matches live $DB_CONTAINER)"
else
  _info "preflight: postgres volume $resolved_volume (external, db container not running)"
fi

_info "preflight: remote backup is deferred for this pilot (not a deploy blocker)"
MARKER="${BACKUP_STATUS_FILE:-/var/lib/onboard-ai-backup/last-backup.json}"
if [ -f "$MARKER" ]; then
  _info "backup marker present at $MARKER"
else
  _info "backup marker absent; continuing (BACKUP/DR deferred — accepted pilot risk)"
fi

if [ "${ONBOARDAI_SKIP_BUILD:-0}" != "1" ]; then
  _info "build images"
  _compose build api bot frontend migrate
fi

_info "run migrations exactly once"
_compose run --rm migrate

_info "restart API (single instance; brief downtime expected)"
_compose up -d --no-deps --force-recreate api

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
_compose up -d --no-deps --force-recreate bot

_info "verify frontend"
curl -fsS "$FRONTEND_URL" >/dev/null || _die "frontend root did not respond"
curl -fsS -o /dev/null -w "%{http_code}" -X POST "$AUTH_URL" \
  -H "content-type: application/json" \
  -d '{}' | grep -Eq '^(400|401|403|422)$' \
  || _die "auth endpoint did not return a basic client error"

_compose exec -T api alembic current >/dev/null \
  || _die "could not read alembic current from API"

_info "smoke checks passed"
_info "If readiness later fails, revert the image only when the last migration is backward compatible."
_info "This script does not roll back automatically."
