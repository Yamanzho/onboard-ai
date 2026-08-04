# OnboardAI Admin Panel

React + Vite SPA for HR/admin Knowledge Base management. Talks to the FastAPI backend at `/api/v1`.

## Prerequisites

- Node.js 20+
- Backend running locally (see root [README](../README.md)): Postgres, Redis, migrations, `uvicorn` on port **8000**

## Setup

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173

Vite proxies `/api` → `http://localhost:8000`, so leave `VITE_API_BASE_URL` empty for local development.

## Login

Use an **employee UUID** (role `admin` or `hr`) and the shared `AUTH_PASSWORD` from the backend `.env`.

## Scripts

| Command        | Description              |
|----------------|--------------------------|
| `npm run dev`  | Dev server (port 5173)   |
| `npm run build`| Production build         |
| `npm run preview` | Preview production build |

## Features (Sprint 2.3)

- Login / JWT session (refresh on 401)
- Dashboard
- Knowledge articles: list, create, edit, publish, archive
- Categories and tags CRUD
- Stub pages: Employees, Onboarding; Settings shows current user
