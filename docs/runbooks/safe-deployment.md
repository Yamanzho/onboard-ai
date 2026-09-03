# Safe deployment and graceful shutdown

Phase 8C makes restarts predictable on the current single-VPS Compose stack.
It does **not** provide high availability or true zero-downtime deploys.

## Architecture

Process-local states:

1. `starting` — process is up, not ready for traffic
2. `ready` — `/ready` may succeed after dependency checks
3. `draining` — SIGTERM/lifespan shutdown; `/ready` fails, `/health` stays 200
4. `stopped` — resources closed

```text
Internet → host nginx → 127.0.0.1:3000 frontend → api:8000
```

There is one API container. nginx cannot route around a draining instance.
During `docker compose up --force-recreate api` the public site is briefly
unavailable. That is expected.

## Health vs readiness

| State | `/health` | `/ready` |
|-------|-----------|----------|
| starting | 200 | 503 `not ready` |
| ready + dependencies up | 200 | 200 |
| ready + PostgreSQL down | 200 | 503 `database unavailable` |
| draining | 200 | 503 `draining` |
| stopped | process gone | process gone |

`/health` is Docker liveness. Transient database problems must not restart the
API container. Monitoring still probes public `/ready`.

Bodies never include URLs, passwords, raw exceptions, or host paths.

## API shutdown

Uvicorn `--timeout-graceful-shutdown` is **45 seconds**.

Why 45:

- Normal AI chat budget is 25 seconds
- Persistence and outbound enqueue need a short remainder
- Frontend nginx proxy timeout is 60 seconds
- Docker `stop_grace_period` is 60 seconds so SIGKILL happens after drain

KB publish/reindex can exceed 45 seconds. That work is lease-protected in
PostgreSQL and is recoverable after restart. Do not raise the grace window to
cover unbounded reindex.

On SIGTERM:

1. Uvicorn stops accepting new connections
2. Lifespan marks `draining` so `/ready` fails
3. In-flight requests continue until 45 seconds
4. Redis and the database engine close with a short timeout
5. Process exits

## Bot shutdown

On SIGTERM:

1. Stop webhook intake or polling
2. Stop claiming new outbound batches
3. Finish the current owned send if time remains
4. Stop heartbeat
5. Close API, Telegram, FSM Redis, and conversation-store Redis clients

Owned `sending` rows that do not finish stay recoverable after the 120s lease.
A send that reached Telegram before the local ack can duplicate after reclaim.
That is the existing outbox contract, not exactly-once delivery.

## Durable recovery

| Work | Shutdown impact | Recovery |
|------|-----------------|----------|
| Idempotency receipts | `processing` may remain if complete never ran | Failed receipts retry immediately; stale processing reclaims after lease (300s Telegram / 120s AI) |
| Telegram outbound | No new claims after drain | Pending/due rows resume; stale `sending` reclaims after 120s |
| KB indexing | Mid-index cancel does not commit partial chunks | Lease expiry (300s) or explicit reindex; prior indexed chunks stay if Phase 7E preserved them |

## Migrations

Every API replica must **not** race `alembic upgrade head`.

- `migrate` is a one-shot Compose service (`APP_ENV=development` so Settings
  does not require serving secrets or hosted AI keys)
- API sets `ONBOARDAI_RUN_STARTUP_MIGRATIONS=0`
- Official deploy runs `docker compose ... run --rm migrate` exactly once
- Then the API container is recreated

Do not start a second API replica that also migrates.

## Compose settings

| Service | stop_signal | stop_grace_period | Docker health |
|---------|-------------|-------------------|---------------|
| migrate | default | default | none (oneshot) |
| api | SIGTERM | 60s | `GET /health` |
| bot | SIGTERM | 60s | local `GET /health` (idle without `BOT_TOKEN` is OK) |
| frontend | SIGTERM | 30s | `GET /` on 8080 |
| db / redis | unchanged | unchanged | existing checks |

## Safe deploy sequence

Prefer `scripts/deploy_production.sh` on the VPS after a backup exists.

1. Preflight: `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`
2. Confirm a recent successful backup marker (Phase 8A)
3. Build images
4. `docker compose ... run --rm migrate`
5. Recreate API only (`--no-deps --force-recreate api`)
6. Wait for `/health` and `/ready`
7. Recreate bot
8. Smoke: frontend `/`, auth endpoint basic response, `alembic current`
9. Confirm monitoring still scrapes API metrics and public probes
10. If `/ready` never returns 200, the deploy is **not** successful

## Failed deploy / rollback

- Do not declare success when readiness fails
- Collect `docker compose logs api` and `alembic current`
- Image rollback is safe only when the last migration is backward compatible
- A non-backward-compatible schema change cannot be undone by restarting the old image
- This repository does not auto-rollback
- Do not delete the Postgres volume to recover a failed deploy

## Single-VPS limits

The following still cause downtime:

- host reboot
- PostgreSQL restart
- host nginx restart
- replacing the one API container

Phase 8C bounds that downtime and keeps durable work recoverable.
It is not HA.

## External availability

Internal Prometheus cannot see total VPS loss. Keep one operator-owned probe
against `https://onboardai.aoe.kz/health` (Phase 8B).
