# OnboardAI

Telegram-first SaaS for AI-powered onboarding.

## Stack

- Python 3.13 / FastAPI / aiogram 3
- PostgreSQL + SQLAlchemy + Alembic
- Redis
- React (Vite) Admin Panel
- Docker Compose

## One-command local start

```bash
cp .env.example .env
docker compose up --build
```

This starts **PostgreSQL**, **Redis**, **API** (migrations + demo seed), **Admin frontend**, and the **Telegram bot** container (idle until `BOT_TOKEN` is set).

| Service   | URL |
|-----------|-----|
| Admin UI  | http://localhost:3000 |
| API       | http://localhost:8000 |
| Health    | http://localhost:8000/health |
| Swagger   | http://localhost:8000/docs |
| Bot webhook port (server mode) | http://localhost:8081/webhook |

### Demo login (seeded automatically)

| Role     | Username (employee UUID)              | Password (`AUTH_PASSWORD`) |
|----------|----------------------------------------|----------------------------|
| HR       | `33333333-3333-4333-8333-333333333333` | `change-me-auth`           |
| Admin    | `22222222-2222-4222-8222-222222222222` | `change-me-auth`           |

- Company ID / `BOT_COMPANY_ID`: `11111111-1111-4111-8111-111111111111`
- Demo employee Telegram id: `100003`

Disable seed: set `SEED_DEMO=false` in `.env`.

Stop:

```bash
docker compose down
```

More detail: [DEPLOYMENT.md](DEPLOYMENT.md).

---

## End-to-end happy path (Admin + Bot)

1. Open http://localhost:3000 → sign in as **Demo HR**.
2. **Employees** → create a new employee (set `telegram_user_id` to your real Telegram user id, status `active`).
3. **Onboarding** → create a program → add steps → **Publish**.
4. **Assignments** → assign the program to that employee.
5. Configure the bot (see below) → in Telegram send `/start` → **Мой онбординг** → complete steps.

---

## Telegram bot

### Required `.env` values

| Variable | Purpose |
|----------|---------|
| `BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) |
| `BOT_COMPANY_ID` | Tenant UUID (demo seed default above) |
| `BOT_SERVICE_TOKEN` | Shared secret for `POST /api/v1/auth/bot/telegram` (must match API) |

### Local testing (polling — recommended)

Leave `BOT_WEBHOOK_URL` **empty**. The bot uses long polling (no public HTTPS URL).

```bash
# 1. Put BOT_TOKEN in .env (BOT_COMPANY_ID already defaults to demo)
# 2. Restart bot (or full stack)
docker compose up --build -d
docker compose logs -f bot
```

Or run the bot on the host (API must be reachable at `API_BASE_URL`):

```bash
source .venv/bin/activate
python -m app.bot
```

### Server testing (webhook)

1. Expose the bot with HTTPS (nginx / Caddy / Cloudflare Tunnel / ngrok).
2. Set:

```env
BOT_WEBHOOK_URL=https://your.domain/webhook
BOT_WEBHOOK_SECRET=some-random-secret
BOT_WEBHOOK_PATH=/webhook
BOT_WEBHOOK_PORT=8081
```

3. Restart the bot container. On startup it calls Telegram `setWebhook`.

Webhook mode is selected automatically when `BOT_WEBHOOK_URL` is non-empty; otherwise polling is used.

### Manual bot checklist

1. Employee exists with your `telegram_user_id` and status `active` in `BOT_COMPANY_ID`.
2. Published program assigned to that employee.
3. In Telegram: `/start` → open **Мой онбординг** → complete each step.
4. In Admin: Dashboard / Assignments show progress / completed.

Without `BOT_TOKEN`, the bot container stays **idle** (`sleep infinity`) so the rest of the stack still runs.

---

## Local development (API on host)

```bash
cp .env.example .env
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

docker compose up -d db redis
alembic upgrade head
python -m scripts.seed_demo

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Admin panel (Vite, proxies `/api` → `:8000`):

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173.

---

## Project layout

`app/` · `frontend/` · `alembic/` · `scripts/` · `docker/` · `tests/`
