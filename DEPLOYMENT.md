# OnboardAI — Deployment guide

This document covers **local Docker Compose** and a minimal **Ubuntu Server** deployment.  
It does not add product features; it only documents how to run what the repo already ships.

---

## 1. Prerequisites

### Local (macOS / Linux / Windows + Docker Desktop)

- Docker Engine + Compose v2
- Free ports: `3000` (UI), `8000` (API), `5432` (Postgres), `6379` (Redis), `8081` (bot webhook, optional)

### Ubuntu Server

- Ubuntu 22.04+ recommended
- Root or sudo
- Public DNS (for webhook HTTPS) if you use Telegram webhook mode
- Open firewall ports as needed (`80`/`443` for reverse proxy; `8000` only if exposed directly)

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
curl -s http://localhost:8000/health
# {"status":"ok"}

open http://localhost:3000
open http://localhost:8000/docs
docker compose ps
docker compose logs -f api
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
| `BOT_COMPANY_ID` | for live bot | Demo default is fine for local |
| `BOT_SERVICE_TOKEN` | yes (API + bot) | Must be identical for API and bot |
| `BOT_WEBHOOK_URL` | webhook mode only | Public `https://…/webhook` |
| `BOT_WEBHOOK_SECRET` | recommended for webhook | Telegram secret token header |
| `BOT_WEBHOOK_PATH` | optional | Default `/webhook` |
| `BOT_WEBHOOK_PORT` | optional | Default `8081` (container listen port) |
| `API_BASE_URL` | auto in Compose | Compose sets `http://api:8000` |

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
AUTH_PASSWORD=<strong password>
BOT_SERVICE_TOKEN=<python -c "import secrets; print(secrets.token_urlsafe(32))">
BOT_TOKEN=<from BotFather>
BOT_COMPANY_ID=11111111-1111-4111-8111-111111111111
BOT_WEBHOOK_URL=https://onboard.example.com/webhook
BOT_WEBHOOK_SECRET=<random>
SEED_DEMO=true   # or false after first bootstrap
```

Bind only localhost for DB/Redis if exposing via reverse proxy only (optional hardening — edit compose ports).

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api
```

### 5.3 Nginx reverse proxy (TLS)

Example site config (`/etc/nginx/sites-available/onboard-ai`):

```nginx
server {
    listen 80;
    server_name onboard.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name onboard.example.com;

    ssl_certificate     /etc/letsencrypt/live/onboard.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/onboard.example.com/privkey.pem;

    # Admin UI + /api proxy (Compose frontend already proxies /api internally;
    # publishing frontend:3000 is enough for a simple setup)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Telegram webhook → bot container
    location /webhook {
        proxy_pass http://127.0.0.1:8081/webhook;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/onboard-ai /etc/nginx/sites-enabled/
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d onboard.example.com
sudo nginx -t && sudo systemctl reload nginx
```

Then set `BOT_WEBHOOK_URL=https://onboard.example.com/webhook` and restart bot:

```bash
docker compose up -d --force-recreate bot
docker compose logs -f bot
```

### 5.4 Migrations & seed on server

Handled automatically by `docker/entrypoint-api.sh` on API start.  
Manual:

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed_demo
```

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

- [ ] Strong `SECRET_KEY` (≥32 bytes) and `AUTH_PASSWORD`
- [ ] Unique `BOT_SERVICE_TOKEN`
- [ ] `DEBUG=false`, `APP_ENV=production`
- [ ] Do not publish Postgres/Redis ports publicly
- [ ] TLS for Admin UI and bot webhook
- [ ] Backups for `postgres_data` volume
- [ ] Decide whether `SEED_DEMO` stays enabled
- [ ] Rotate demo passwords / remove demo users on real tenants
- [ ] Monitor `docker compose logs` for API/bot errors
