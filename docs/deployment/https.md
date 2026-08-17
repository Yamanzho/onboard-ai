# HTTPS / DNS cutover (manual production steps)

This document prepares **onboardai.aoe.kz** for HTTPS. It does **not**
configure DNS, issue a certificate, or deploy anything.

| Item | Status in this repository |
|------|---------------------------|
| Host Nginx HTTP site | Prepared (`deploy/nginx/onboardai.aoe.kz.conf`) |
| DNS A record | **Not configured** — create in PS Cloud Services |
| Let's Encrypt certificate | **Not issued** — run Certbot on the VPS later |
| Production `.env` | **Not modified by this document** |

Do not run Certbot, `nginx -t` on production, or container restarts from this
checkout. Those are VPS operator steps listed below.

## Target

```text
onboardai.aoe.kz
        ↓  A record (manual)
185.146.1.22
        ↓  host Nginx :80 then :443
127.0.0.1:3000  Compose frontend (nginx.prod.conf)
        ↓  Docker network
api:8000        FastAPI (no host port in production)
db / redis      Docker network only (not published)
```

Do **not** publish PostgreSQL, Redis, or the API on the public internet.
Do **not** bind the production frontend to `0.0.0.0`.
Do **not** proxy `/api` from host Nginx to `:8000` — production API has no
host port. Frontend nginx proxies `/api/` → `http://api:8000/api/`.

The API container still listens on `0.0.0.0:8000` **inside** the Compose
network so `frontend` can reach `api:8000`. Binding it to `127.0.0.1` inside
the container would break Docker DNS. Host exposure is removed by
`docker-compose.prod.yml` (`ports: !reset []`).

## Exact PS DNS action

In the **PS Cloud Services** DNS panel for `aoe.kz`:

| Field | Value |
|-------|--------|
| Type | `A` |
| Host | `onboardai` |
| Value | `185.146.1.22` |

Result: `onboardai.aoe.kz` → `185.146.1.22`.

Do **not** add `www` unless product later requires it.
Do **not** change DNS from this repository.

## Phase 1 — HTTP only

Required before Let's Encrypt HTTP-01.

The shipped Nginx site listens on **:80 only**. It does not reference
`/etc/letsencrypt/...` files. Those files do not exist until Phase 2.

Health: `GET /health` → frontend nginx → API `{"status":"ok"}`.
OpenAPI `/docs`, `/redoc`, `/openapi.json` stay 404 at the production frontend.

Cookie login on Phase 1 HTTP will **not** stick: `APP_ENV=production` sets
`Secure` cookies (`app/core/auth_cookies.py`). Verify login cookies in Phase 2.

## Phase 2 — HTTPS

After DNS answers, Certbot patches the same Nginx site to add :443,
certificate paths, and HTTP→HTTPS redirect.

Expected paths **after** a successful Certbot run (not in git):

- `/etc/letsencrypt/live/onboardai.aoe.kz/fullchain.pem`
- `/etc/letsencrypt/live/onboardai.aoe.kz/privkey.pem`

HSTS belongs on the TLS edge **after** HTTPS-only is confirmed. Do not enable
HSTS during Phase 1 HTTP.

## INVITE_BASE_URL

Application code reads `INVITE_BASE_URL` (`app.core.config.invite_base_url`).
Invite and password-reset links are `{INVITE_BASE_URL}/invite#…` and
`{INVITE_BASE_URL}/reset-password#…`.

| Environment | Value |
|-------------|--------|
| Local / `.env.example` | `http://localhost:3000` |
| Production target | `https://onboardai.aoe.kz` |

Set production `.env` on the VPS (do not commit it):

```bash
INVITE_BASE_URL=https://onboardai.aoe.kz
```

Then restart **api** only. Do not hardcode the hostname in Python.

## CORS

The production SPA is **same-origin**: `VITE_API_BASE_URL` is empty, the
browser calls `/api/...` on `https://onboardai.aoe.kz`, and frontend nginx
proxies to the API. FastAPI does **not** install `CORSMiddleware`.

Do **not** add `Access-Control-Allow-Origin: *` for credentialed cookies.
Local Vite (`npm run dev`) uses the empty base URL plus the Vite proxy; do
not point the production build at a cross-origin API.

## Cookies

| Flag | Production (`APP_ENV=production`) | Development |
|------|-----------------------------------|-------------|
| HttpOnly | yes | yes |
| Secure | yes (`settings.is_production`) | no |
| SameSite | `Lax` | `Lax` |
| Domain | unset (host-only) | unset |
| Path | `/` | `/` |

Do not set `AUTH_COOKIE_SECURE=false`. Do not change SameSite for this cutover.

## Proxy headers

Host Nginx overwrites `X-Real-IP` / `X-Forwarded-For` with `$remote_addr`
(never `$proxy_add_x_forwarded_for`) and sets `X-Forwarded-Proto $scheme`.

Frontend `nginx.prod.conf` overwrites client-IP headers again toward the API
(SEC-R1) and **passes through** `X-Forwarded-Proto` from the host so the API
sees `https` after TLS terminates at Nginx.

Production Uvicorn uses `--proxy-headers --forwarded-allow-ips='*'` only
because the API has **no host port**. Do not publish `:8000` while that is
enabled. Development keeps `TRUST_PROXY_HEADERS=false` and no proxy-headers
flag.

## Exact VPS commands (manual)

Replace `/opt/onboard-ai` if the clone lives elsewhere. Do not run these from
a laptop against production as part of this documentation task.

```bash
# 1. DNS A record already created in PS Cloud (manual panel).
# 2. Verify DNS from anywhere:
dig +short onboardai.aoe.kz
# expect: 185.146.1.22

# 3. SSH to the VPS (operator).
# 4. Install Nginx (if missing):
sudo apt-get update
sudo apt-get install -y nginx

# 5. Enable HTTP config (Phase 1):
sudo cp /opt/onboard-ai/deploy/nginx/onboardai.aoe.kz.conf \
  /etc/nginx/sites-available/onboardai.aoe.kz
sudo ln -sf /etc/nginx/sites-available/onboardai.aoe.kz /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 6. Validate:
sudo nginx -t

# 7. Reload:
sudo systemctl reload nginx

# 8. Verify HTTP (no certificate yet):
curl -I http://onboardai.aoe.kz
curl -fsS http://onboardai.aoe.kz/health

# 9. Install Certbot:
sudo apt-get install -y certbot python3-certbot-nginx

# 10. Issue Let's Encrypt certificate (MANUAL — do not run until DNS works):
sudo certbot --nginx -d onboardai.aoe.kz

# 11. Verify HTTPS:
curl -I https://onboardai.aoe.kz
curl -fsS https://onboardai.aoe.kz/health

# 12. Verify certificate:
openssl s_client -connect onboardai.aoe.kz:443 -servername onboardai.aoe.kz </dev/null

# 13. Test renewal:
sudo certbot renew --dry-run

# 14. Set invite URL in the VPS .env (do not commit):
# INVITE_BASE_URL=https://onboardai.aoe.kz

# 15. Restart only the API (picks up INVITE_BASE_URL):
cd /opt/onboard-ai
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d api

# 16. Smoke:
curl -fsS https://onboardai.aoe.kz/health
curl -fsSI https://onboardai.aoe.kz/login | tr -d '\r' | grep -i '^set-cookie' || true
ss -lntp | egrep ':80|:443|:3000|:8000|:5432|:6379'
```

Firewall (if UFW is used):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

Compose command for the application stack (already the production contract):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## Health

| Path | Who serves it | Public? |
|------|----------------|---------|
| `GET /health` | API via frontend nginx | yes — liveness `{"status":"ok"}` |
| `GET /docs` `/redoc` `/openapi.json` | blocked in production | no |
| Super Admin UI routes | SPA, cookie auth | yes, but unauthenticated API is 401 |

## Related files

- `deploy/nginx/onboardai.aoe.kz.conf` — host HTTP site (Certbot-ready)
- `frontend/nginx.prod.conf` — container proxy `/api` + `/health`
- `docker-compose.prod.yml` — loopback frontend, unpublished API/DB/Redis
- `DEPLOYMENT.md` — broader production contract
