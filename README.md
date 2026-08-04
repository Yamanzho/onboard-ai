# OnboardAI

Telegram-first SaaS for AI-powered onboarding.

## Stack

- Python 3.13
- FastAPI
- aiogram 3
- PostgreSQL + SQLAlchemy + Alembic
- Redis
- Docker

## Quick start (all-in-Docker)

```bash
cp .env.example .env
docker compose up --build
docker compose exec api alembic upgrade head
```

API health check: `GET http://localhost:8000/health`  
Swagger UI: http://localhost:8000/docs

## Local development

Run the API on the host; PostgreSQL and Redis via Docker Compose.

### Prerequisites

- Python 3.13+
- Docker / Docker Compose
- `pip` (or another Python package installer)

### 1. Environment file

```bash
cp .env.example .env
```

Edit secrets if needed (`SECRET_KEY`, `AUTH_PASSWORD`, `BOT_SERVICE_TOKEN`).  
Keep `DATABASE_URL` and `REDIS_URL` pointing at `localhost` for host-local API.

### 2. Install dependencies

```bash
python3.13 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Start PostgreSQL (and Redis)

```bash
docker compose up -d db redis
```

Wait until both are healthy:

```bash
docker compose ps
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Start FastAPI

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Open Swagger UI

- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health: http://localhost:8000/health

Authenticate via **Auth** → `POST /api/v1/auth/login` (employee UUID + `AUTH_PASSWORD`), then click **Authorize** with the Bearer access token.

### Optional: Telegram bot

Requires `BOT_TOKEN`, `BOT_COMPANY_ID`, and `BOT_SERVICE_TOKEN` in `.env`.

```bash
# host-local bot (API must already be running on :8000)
python -m app.bot

# or via Compose (profile)
docker compose --profile bot up --build bot
```

### Stop infra

```bash
docker compose stop db redis
# or tear down containers (keeps volumes):
docker compose down
```

### Admin Panel (frontend)

With the API running on port 8000:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173 — see [frontend/README.md](frontend/README.md).

## Project layout

See repository root folders: `app/`, `frontend/`, `alembic/`, `tests/`, `scripts/`, `docker/`.
