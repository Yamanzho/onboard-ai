# OnboardAI — Deployment guide

This document covers **local Docker Compose** and a minimal **Ubuntu Server** deployment.  
It does not add product features; it only documents how to run what the repo already ships.

---

## 1. Prerequisites

### Local (macOS / Linux / Windows + Docker Desktop)

- Docker Engine + Compose v2
- Free ports: `3000` (UI), `8000` (API — **local/dev only**), `5432` (Postgres on localhost), `6379` (Redis on localhost, **dev only / no password**), `8081` (bot webhook on localhost)

### Ubuntu Server

- Ubuntu 22.04+ recommended
- Root or sudo
- Public DNS (for webhook HTTPS) if you use Telegram webhook mode
- Open firewall ports as needed (`80`/`443` for reverse proxy). **Do not** expose API `:8000` publicly — use frontend nginx and `docker-compose.prod.yml`. Production frontend binds to `127.0.0.1` only (TLS edge on the host).

---

## 2. Local launch (one command)

```bash
git clone <your-repo-url> onboard-ai
cd onboard-ai
cp .env.example .env
# Optional: set BOT_TOKEN from @BotFather for live Telegram testing
docker compose up --build
```

What starts:

| Compose service | Role |
|-----------------|------|
| `db` | PostgreSQL 16 |
| `redis` | Redis 7 |
| `api` | FastAPI — waits for DB, runs `alembic upgrade head`, seeds demo tenant, serves API |
| `frontend` | Nginx + built React admin (proxies `/api` → `api:8000`) |
| `bot` | Telegram bot — **polling** if `BOT_WEBHOOK_URL` empty; **idle** if `BOT_TOKEN` empty |

### Verify

```bash
# Local/dev compose publishes API for convenience:
curl -s http://localhost:8000/health
# {"status":"ok"}

# Prefer same-origin via frontend nginx (also works in production compose):
curl -s http://localhost:3000/health
# {"status":"ok"}

open http://localhost:3000
open http://localhost:8000/docs   # local/dev only — Swagger/OpenAPI; not available in production
docker compose ps
docker compose logs -f api
```

### OpenAPI / Swagger / ReDoc (P0-05)

| Mode | Swagger `/docs` | OpenAPI `/openapi.json` | ReDoc `/redoc` |
|------|-----------------|-------------------------|----------------|
| **Development** (`docker compose up`, `APP_ENV` ≠ `production`) | Available (API `:8000`, and via frontend nginx proxy) | Available | Available |
| **Production** (`-f docker-compose.prod.yml`, `APP_ENV=production`) | **Disabled** (FastAPI `404`; nginx `404`) | **Disabled** | **Disabled** |

Production disables documentation at the **backend** (`docs_url` / `redoc_url` / `openapi_url` = `None` when `APP_ENV=production`) and at the **edge** (`frontend/nginx.prod.conf` returns `404` for those paths; does not proxy them).

If you need the production API contract while developing, use a local development environment (or a private internal docs setup). Do **not** publish a public docs endpoint in production.

### Production secrets (P0-02)

When `APP_ENV=production`, the API **fail-fast** rejects missing or obviously weak critical secrets (values are never echoed in error messages):

| Variable | Rule |
|----------|------|
| `SECRET_KEY` | Required; ≥ 32 chars; not a known default/placeholder |
| `SUPER_ADMIN_PASSWORD` | Required; ≥ 12 chars; not a known default/placeholder |
| `REDIS_URL` / `REDIS_PASSWORD` | Redis URL must embed a non-empty password (P0-03) |
| `DATABASE_URL` / `POSTGRES_PASSWORD` | Postgres URL password required; ≥ 12 chars; not a known default (SEC-R2) |

`docker-compose.prod.yml` also refuses to interpolate if `SECRET_KEY`, `SUPER_ADMIN_PASSWORD`, `REDIS_PASSWORD`, or `POSTGRES_PASSWORD` is missing/empty.

Generate secrets (do not copy placeholders from `.env.example` into production):

```bash
openssl rand -hex 32                                          # SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(24))"  # SUPER_ADMIN_PASSWORD
python -c "import secrets; print(secrets.token_urlsafe(32))"  # REDIS_PASSWORD
python -c "import secrets; print(secrets.token_urlsafe(32))"  # POSTGRES_PASSWORD
```

Development keeps convenient local defaults; production validation does not apply when `APP_ENV` ≠ `production`.

### Production Redis is required (P1-REDIS)

When `APP_ENV=production`, **Redis is a hard dependency** — services must not silently degrade to process-local memory:

| Component | Production | Development |
|-----------|------------|-------------|
| Bot FSM storage | Must initialize `RedisStorage`; failure **raises** (container exits/restarts). **No** `MemoryStorage` fallback. | Falls back to `MemoryStorage` if Redis is down (**dev-only**; not shared/durable) |
| API login rate limits | Redis required; connect/command failure → **HTTP 503**. **No** per-process memory fallback (would break shared limits across `UVICORN_WORKERS`). | In-memory fallback if Redis is unavailable (**dev-only**; not shared across workers) |

Error messages never include Redis passwords. `/health` remains a **liveness** probe (`{"status":"ok"}`) without Redis credentials; Redis outages surface at bot startup and on rate-limited login endpoints.

Do **not** run production with Redis intentionally down.

### Trust proxy headers (rate limits) — F-04

Login / bot-login / refresh / invite / Super Admin rate limits key by client IP.
Application default is **fail-closed**: `TRUST_PROXY_HEADERS=false` (Settings + `.env.example`).

| Mode | `TRUST_PROXY_HEADERS` | API host port | Safe? |
|------|----------------------|---------------|-------|
| Local/dev (`docker compose up`) | **false** (default) | published `:8000` | Yes — spoofed `X-Forwarded-For` / `X-Real-IP` ignored |
| Production (`-f docker-compose.prod.yml`) | **true** (explicit prod override; trusted nginx → api) | **not published** | Yes — only frontend/bot reach API; nginx overwrites client IP headers |

**SEC-R1 / F-04 contract (trusted single-proxy deployment):**

- The reverse proxy **must overwrite** `X-Real-IP` and `X-Forwarded-For` with `$remote_addr`.
- Do **not** preserve client-supplied `X-Forwarded-For` (never `$proxy_add_x_forwarded_for` for the hop that the API trusts).
- `TRUST_PROXY_HEADERS=true` assumes the API is reachable **only** through that trusted proxy.
- Publishing the API directly while `TRUST_PROXY_HEADERS=true` lets clients spoof `X-Real-IP` / `X-Forwarded-For` and **must not be done**.
- Production Compose keeps API ports empty and binds the frontend to **127.0.0.1** so a typical “open the ports” mistake does not expose the trusted-proxy path to the internet.

### PostgreSQL password vs volume (F-03)

**WARNING:** On an existing `postgres_data` volume, changing `POSTGRES_PASSWORD` in `.env` does **not** rotate the live PostgreSQL role password. The official image applies `POSTGRES_PASSWORD` only on **first** initialization.

- Application roles (`onboard_app`, `onboard_owner`): updated from `ONBOARD_*_PASSWORD` by `scripts/bootstrap_rls_roles.py` on API start.
- Bootstrap role (`POSTGRES_USER`): requires an explicit `ALTER ROLE` / `\password` inside Postgres, then matching `.env`.

Full procedure (backup, verification, rollback; **no** volume wipe as rotation):
[`docs/runbooks/postgres-password-rotation.md`](docs/runbooks/postgres-password-rotation.md).

### Production Compose (immutable images + Redis auth)

```bash
# Required production secrets (generate — do not use .env.example placeholders):
#   SECRET_KEY=$(openssl rand -hex 32)
#   SUPER_ADMIN_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
#   REDIS_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
#   POSTGRES_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
# Add those to .env. APP_ENV/DEBUG are forced by compose.prod.yml.
# Weak/default secrets are rejected at API startup (Settings fail-fast).

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
**Development** (`docker compose up`):

- Bind-mounts `.:/app` on API/bot for hot reload
- `uvicorn --reload` when `APP_ENV` is not `production`
- API published on `:8000`; Redis passwordless on `127.0.0.1`
- Postgres default `onboard`/`onboard` on `127.0.0.1:5432`

**Production** (`-f docker-compose.prod.yml`):

- **No** source bind-mounts — application code is baked into the image (`Dockerfile` `COPY`)
- Forces `APP_ENV=production` and `DEBUG=false` (ignores development values from `.env` for those keys)
- Requires `SECRET_KEY`, `SUPER_ADMIN_PASSWORD`, `REDIS_PASSWORD`, and `POSTGRES_PASSWORD` at compose interpolate time (`:?`)
- API Settings fail-fast on weak/default `SECRET_KEY` / `SUPER_ADMIN_PASSWORD` / unauthenticated Redis / weak Postgres password
- API: `uvicorn … --workers ${UVICORN_WORKERS:-2}` — **no** `--reload`
- Bot: `python -m app.bot` from the image (no reload)
- API has **no** host port — browsers use frontend nginx → `api:8000`
- Redis has **no** host port and requires `--requirepass` (`REDIS_PASSWORD`)
- Postgres has **no** host port and requires `POSTGRES_PASSWORD` (no `onboard` default)
- Bot webhook binds to **127.0.0.1 only** (unchanged host-nginx webhook path)
- Frontend nginx uses **`nginx.prod.conf`**: `/docs`, `/redoc`, `/openapi.json` return **404** (not proxied)
- FastAPI with `APP_ENV=production` sets `docs_url` / `redoc_url` / `openapi_url` to **None**
- Named volumes only: `postgres_data`, `redis_data` (data, not source)
- Frontend host bind is **127.0.0.1 only** (TLS edge on the host; see §5.3 / public edge contract)
- API/bot containers run as non-root UID **10001** (`Dockerfile` `USER onboard`)
- Frontend nginx listens on **8080** as `USER nginx` (host still maps `127.0.0.1:3000`)
- Access JWTs carry exact `iss` / `aud` (`JWT_ISSUER` / `JWT_AUDIENCE`)
- New passwords use **Argon2id**; legacy PBKDF2 verifies and upgrades on login
- Invite email links use `/invite#<token>` (fragment); preview is `POST /api/v1/auth/invite/preview`
- Legacy SPA route `/invite/:token` remains temporarily so invitations issued before the fragment cutover stay redeemable. New emails always use `/invite#<token>`. Default `INVITE_TTL_HOURS=24`; remove the path route only after that TTL window has elapsed with no outstanding path-based links (earliest safe removal: 24h after last path-link send, or a documented cutover date). Invite tokens are stored hashed only — never plaintext.

| Service | Dev host ports | Prod host ports | Source mount |
|---------|----------------|-----------------|--------------|
| `frontend` | `*:3000` → container `8080` | **127.0.0.1:3000** → container `8080` (non-root nginx) | none (built image) |
| `api` | `*:8000` | **none** | dev: `.:/app` / prod: **none** |
| `redis` | `127.0.0.1:6379` (no password) | **none** + password | n/a |
| `bot` | `127.0.0.1:8081` | `127.0.0.1:8081` | dev: `.:/app` / prod: **none** |
| `db` | `127.0.0.1:5432` | **none** + password | data volume |

Validate:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
# api.ports / redis.ports empty
# api/bot volumes must not include bind mounts to /app
# api environment APP_ENV=production
# redis command includes requirepass

curl -s http://localhost:8000/health   # should fail (connection refused)
curl -s http://localhost:3000/health   # ok via nginx
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/docs         # 404
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/openapi.json # 404
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/redoc        # 404
```

### Demo credentials (auto-seed)
| Field | Value |
|-------|--------|
| HR login UUID | `33333333-3333-4333-8333-333333333333` |
| Admin login UUID | `22222222-2222-4222-8222-222222222222` |
| Password | value of `AUTH_PASSWORD` in `.env` (default `change-me-auth`) |
| `BOT_COMPANY_ID` | `11111111-1111-4111-8111-111111111111` |
| Demo employee `telegram_user_id` | `100003` |

Re-seed manually:

```bash
docker compose exec api python -m scripts.seed_demo
```

Disable seed: `SEED_DEMO=false` in `.env`, then recreate the API container.

### Stop / reset

```bash
docker compose down          # keep DB volume
docker compose down -v       # wipe Postgres + Redis data
```

---

## 3. Manual product scenario (Admin → Bot)

1. **HR Login** — http://localhost:3000 with Demo HR UUID + `AUTH_PASSWORD`.
2. **Create employee** — Employees → New. Use your real Telegram user id; status `active`.
3. **Create program** — Onboarding → New program.
4. **Create steps** — open the program → add content/task/quiz/ack steps; reorder if needed.
5. **Publish** — Publish on the program detail/list.
6. **Assignment** — Assignments → New → pick employee + published program.
7. **Telegram** — with `BOT_TOKEN` set and bot running:
   - `/start`
   - **Мой онбординг**
   - complete steps until the program finishes
8. Confirm progress on Dashboard / Assignment detail.

---

## 4. Telegram bot configuration

### Environment variables

| Variable | Required | Notes |
|----------|----------|-------|
| `BOT_TOKEN` | for live bot | From BotFather |
| `BOT_COMPANY_ID` | for live bot | **Required** with `BOT_SERVICE_TOKEN`. One bot process = one company (see below). |
| `BOT_SERVICE_TOKEN` | yes (API + bot) | Must be identical for API and bot; compared with `secrets.compare_digest` |
| `BOT_WEBHOOK_URL` | webhook mode only | Public `https://…/webhook` |
| `BOT_WEBHOOK_SECRET` | recommended for webhook | Telegram secret token header |
| `BOT_WEBHOOK_PATH` | optional | Default `/webhook` |
| `BOT_WEBHOOK_PORT` | optional | Default `8081` (container listen port) |
| `API_BASE_URL` | auto in Compose | Compose sets `http://api:8000` |

### Bot tenancy model (F-08)

`BOT_COMPANY_ID` is a **security binding**, not optional metadata:

- One bot **process** serves **one** company (single-tenant process architecture).
- The API rejects bot login unless the request `company_id` **exactly equals** the server `BOT_COMPANY_ID`.
- Telegram / client-supplied company ids are **never** authorization truth.
- Cross-tenant bot access remains impossible without a stolen service token **and** matching company binding.

This is an intentional **scalability/ops** limit (run N bot processes for N companies), not a missing security control. Do **not** remove the binding to “support multi-tenant bots” without a server-side routing table that still ignores client-supplied company ids.

### Polling (local)

1. Set `BOT_TOKEN` in `.env`.
2. Leave `BOT_WEBHOOK_URL` empty.
3. `docker compose up --build -d && docker compose logs -f bot`
4. Expect log: `Starting bot in polling mode`.

### Webhook (server)

1. Terminate TLS to the bot port (or reverse-proxy path `/webhook` → `127.0.0.1:8081`).
2. Set `BOT_WEBHOOK_URL=https://your.domain/webhook` (and optional `BOT_WEBHOOK_SECRET`).
3. Restart bot. Expect log: `Webhook set to …`.

### Host-local bot (without Compose bot service)

```bash
# API already on :8000, DB/Redis up
export BOT_TOKEN=...
export BOT_COMPANY_ID=11111111-1111-4111-8111-111111111111
export BOT_SERVICE_TOKEN=...   # same as API .env
export API_BASE_URL=http://localhost:8000
python -m app.bot
```

---

## 5. Ubuntu Server (Compose behind Nginx)

### 5.1 Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# re-login for group membership
```

### 5.2 Deploy app

```bash
sudo mkdir -p /opt/onboard-ai
sudo chown "$USER":"$USER" /opt/onboard-ai
cd /opt/onboard-ai
git clone <your-repo-url> .
cp .env.example .env
nano .env   # set strong SECRET_KEY, AUTH_PASSWORD, BOT_SERVICE_TOKEN, BOT_TOKEN, …
```

Recommended production `.env` highlights:

```env
APP_ENV=production
DEBUG=false
SECRET_KEY=<openssl rand -hex 32>
SUPER_ADMIN_PASSWORD=<python -c "import secrets; print(secrets.token_urlsafe(24))">
AUTH_PASSWORD=<strong password — shared login disabled in production anyway>
BOT_SERVICE_TOKEN=<python -c "import secrets; print(secrets.token_urlsafe(32))">
BOT_TOKEN=<from BotFather>
BOT_COMPANY_ID=11111111-1111-4111-8111-111111111111
BOT_WEBHOOK_URL=https://onboard.example.com/webhook
BOT_WEBHOOK_SECRET=<random>
REDIS_PASSWORD=<python -c "import secrets; print(secrets.token_urlsafe(32))">
POSTGRES_PASSWORD=<python -c "import secrets; print(secrets.token_urlsafe(32))">
SEED_DEMO=true   # or false after first bootstrap
```

Do **not** paste angle-bracket placeholders or documented demo defaults (`change-me*`, `onboard`) into a production `.env` — Settings will refuse to start.
For production use `docker-compose.prod.yml`: **API, Redis, and Postgres are not published** on the host;
Redis requires `REDIS_PASSWORD`; Postgres requires `POSTGRES_PASSWORD`. Frontend plaintext is
**127.0.0.1:3000** only — terminate TLS at host nginx and proxy to that address
(see §5.3 public edge contract / Trust proxy). Bot webhook stays on `127.0.0.1:8081` for
host nginx → Telegram webhook (unchanged path).
Changing `POSTGRES_PASSWORD` on an existing volume is **not** a password rotation — see
[`docs/runbooks/postgres-password-rotation.md`](docs/runbooks/postgres-password-rotation.md).

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
docker compose ps
docker compose logs -f api
```

### 5.3 Public TLS / edge contract (F-07)

TLS termination is **outside** Compose by design. Public production **requires** this topology:

```text
Internet
  → TLS terminator / reverse proxy (host; TLS 1.2+, prefer 1.3; valid cert + renewal)
    → 127.0.0.1:3000 (Compose frontend / nginx.prod.conf)
      → api:8000 (Docker internal network only)
    → 127.0.0.1:8081 (bot webhook, if used)
  ↛ API :8000, Postgres :5432, Redis :6379, and frontend plaintext must NOT be public
```

| Expectation | Production posture |
|-------------|-------------------|
| API host port | **None** (`docker-compose.prod.yml`) |
| Postgres / Redis host ports | **None** |
| Frontend plaintext | **127.0.0.1 only** — not a public listener |
| HTTP → HTTPS redirect | On the TLS edge (example below) |
| Secure cookies | On when `APP_ENV=production` (`Secure` flag) |
| HSTS | Enable on the edge **after** confirming HTTPS-only (includeSubDomains only if all subdomains are ready) |
| Trusted proxy boundary | Host edge → frontend; frontend nginx overwrites `X-Real-IP` / `XFF` toward API |
| Firewall / security groups | Allow `80`/`443` to the edge only; deny public `3000`/`8000`/`5432`/`6379`/`8081` |

Documentation is not a substitute for the compose port resets and localhost binds above.

### 5.4 Nginx reverse proxy (TLS)

Canonical cutover (DNS, HTTP-first, Certbot, `INVITE_BASE_URL`):
[`docs/deployment/https.md`](docs/deployment/https.md).

Host site file (HTTP-first, no certificate paths until Certbot runs):
`deploy/nginx/onboardai.aoe.kz.conf`.

Terminate TLS on the host and proxy to the Compose **frontend** (`127.0.0.1:3000`). Prefer this over exposing the API. The frontend container (`nginx.prod.conf`) already overwrites `X-Real-IP` / `X-Forwarded-For` with `$remote_addr` when talking to the API (SEC-R1) and sends a restrictive Content-Security-Policy (F-06).

If you also set those headers on the host edge (or if you ever proxy `/api` to the API yourself), use the same **overwrite** contract — never `$proxy_add_x_forwarded_for`, which preserves a client-spoofed `X-Forwarded-For` and can reintroduce a rate-limit bypass when `TRUST_PROXY_HEADERS=true`.

Phase 1 HTTP site (shipped; Certbot later adds :443). Do **not** copy a `ssl_certificate` block before files exist:

```nginx
server {
    listen 80;
    server_name onboardai.aoe.kz;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Admin UI + /api via Compose frontend (frontend nginx → api:8000).
    # SEC-R1: overwrite client IP headers with $remote_addr — do NOT use
    # $proxy_add_x_forwarded_for (that preserves client-supplied XFF).
    # TRUST_PROXY_HEADERS=true requires the API to be reachable only via a
    # trusted proxy; never publish API:8000 to the public internet.
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Telegram webhook → bot container (127.0.0.1 bind only)
    location /webhook {
        proxy_pass http://127.0.0.1:8081/webhook;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Manual production steps (do not run from this documentation task):

```bash
sudo cp /opt/onboard-ai/deploy/nginx/onboardai.aoe.kz.conf \
  /etc/nginx/sites-available/onboardai.aoe.kz
sudo ln -sf /etc/nginx/sites-available/onboardai.aoe.kz /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d onboardai.aoe.kz
```

Then set `INVITE_BASE_URL=https://onboardai.aoe.kz` in the VPS `.env` and restart **api**.
If Telegram webhook mode is used, set `BOT_WEBHOOK_URL=https://onboardai.aoe.kz/webhook` and recreate **bot** only:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate bot
docker compose logs -f bot
```

### 5.5 Migrations & seed on server

Handled automatically by `docker/entrypoint-api.sh` on API start (runs as non-root UID 10001).
Manual:

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed_demo
```

PostgreSQL password rotation on an existing volume:
[`docs/runbooks/postgres-password-rotation.md`](docs/runbooks/postgres-password-rotation.md).

---

## 6. Host-local hybrid (dev without full Compose app stack)

```bash
cp .env.example .env
docker compose up -d db redis
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m scripts.seed_demo
uvicorn app.main:app --reload --port 8000
# other terminal:
cd frontend && npm install && npm run dev
```

---

## 7. Troubleshooting

| Symptom | Check |
|---------|--------|
| API unhealthy | `docker compose logs api` — DB URL, migrations |
| Frontend 502 on `/api` | API health; frontend depends on healthy API |
| Login fails | Use **employee UUID**, not email; password = `AUTH_PASSWORD` |
| Bot idle | `BOT_TOKEN` empty — expected; set token and recreate bot |
| Bot can't auth employee | `telegram_user_id` mismatch; `BOT_COMPANY_ID` wrong; `BOT_SERVICE_TOKEN` mismatch |
| Webhook not receiving | Public HTTPS, path, firewall, `getWebhookInfo` via Bot API |
| Port in use | Stop host `uvicorn`/`vite` or change `API_PORT` / `FRONTEND_PORT` |

---

## 8. Before production (checklist)

- [ ] Strong unique `SECRET_KEY` (≥32 chars; not a default/placeholder)
- [ ] Strong unique `SUPER_ADMIN_PASSWORD` (≥12 chars; not a default/placeholder)
- [ ] Strong `AUTH_PASSWORD` if still used for any legacy bootstrap (shared login is off in production)
- [ ] Unique `BOT_SERVICE_TOKEN`
- [ ] Strong unique `POSTGRES_PASSWORD` (≥12 chars; not `onboard` / other defaults)
- [ ] Strong unique `ONBOARD_OWNER_PASSWORD` / `ONBOARD_APP_PASSWORD` (distinct from bootstrap)
- [ ] Understand F-03: editing `POSTGRES_PASSWORD` alone does not rotate an existing volume ([runbook](docs/runbooks/postgres-password-rotation.md))
- [ ] `DEBUG=false`, `APP_ENV=production`
- [ ] Do not publish Postgres/Redis/API ports publicly (prod: no host ports; passwords required)
- [ ] Frontend plaintext bound to `127.0.0.1` only; TLS edge in front
- [ ] Production uses `docker-compose.prod.yml` (immutable images; no `.:/app`; no `--reload`; secrets required; non-root API/bot)
- [ ] TLS 1.2+ (prefer 1.3) for Admin UI and bot webhook; HTTP→HTTPS on edge; HSTS after HTTPS-only confirmed
- [ ] `TRUST_PROXY_HEADERS=true` only with trusted overwrite proxy and unpublished API
- [ ] Backups for `postgres_data` volume (+ restore drill)
- [ ] Decide whether `SEED_DEMO` stays enabled
- [ ] Rotate demo passwords / remove demo users on real tenants
- [ ] Monitor `docker compose logs` for API/bot errors
