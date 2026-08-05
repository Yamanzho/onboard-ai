# OnboardAI Admin Panel

React + Vite SPA for HR/admin management. Talks to the FastAPI backend at `/api/v1`.

## Preferred: Docker Compose

From the repository root (see root [README](../README.md)):

```bash
cp .env.example .env
docker compose up --build
```

Admin UI: **http://localhost:3000** (Nginx serves the production build and proxies `/api` → API).

## Local Vite (API on host)

```bash
# API must already be on :8000
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` → `http://localhost:8000`.

## Login

Use an **employee UUID** (`admin` or `hr`) and `AUTH_PASSWORD` from backend `.env`.

Demo HR (after seed): `33333333-3333-4333-8333-333333333333` / `change-me-auth`.

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Dev server (port 5173) |
| `npm run build` | Production build |
| `npm run preview` | Preview production build |
