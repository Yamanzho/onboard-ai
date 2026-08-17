# Host nginx TLS edge

Canonical cutover: [docs/deployment/https.md](../../docs/deployment/https.md).

Production topology:

```text
Internet
  → host nginx (:80 HTTP-first, then :443 TLS)
    → 127.0.0.1:3000 (Compose frontend / nginx.prod.conf)
      → api:8000 (Docker internal only)
    → 127.0.0.1:8081 (bot webhook)
```

PostgreSQL and Redis stay on the Compose network (no host ports in production).

This directory ships **HTTP-first** (`onboardai.aoe.kz.conf`). It does **not**
reference Let's Encrypt certificate files. Those files do not exist until a
manual Certbot run on the VPS. After certificates exist, replace the site
with `onboardai.aoe.kz.https.conf` (HTTP→HTTPS redirect, TLS 1.2/1.3, HSTS).

## Rules

1. Use `docker compose -f docker-compose.yml -f docker-compose.prod.yml` only.
2. **Never** stack `docker-compose.ip.yml` in production — it publishes `0.0.0.0:3000` and sets `AUTH_COOKIE_SECURE=false`.
3. Frontend must stay on `127.0.0.1:3000`.
4. Do not publish API `:8000`, Postgres, or Redis.
5. Do not proxy `/api` from host Nginx to `:8000`. Frontend nginx proxies `/api` → `api:8000` on the Compose network.
6. Enable `TRUST_PROXY_HEADERS=true` only with this unpublished-API topology. The edge **overwrites** `X-Real-IP` / `X-Forwarded-For` with `$remote_addr` (never `$proxy_add_x_forwarded_for`).
7. Enable HSTS only on the HTTPS site (`onboardai.aoe.kz.https.conf`) after HTTP redirects to HTTPS.

## DNS prerequisite (manual)

In the PS Cloud Services panel, create:

| Type | Host | Value |
|------|------|-------|
| A | `onboardai` | `185.146.1.22` |

Result: `onboardai.aoe.kz` → `185.146.1.22`. Do not add `www` unless product requires it.

Verify before Certbot:

```bash
dig +short onboardai.aoe.kz
# expect: 185.146.1.22
```

DNS is **not** configured by this repository. Do not claim it is.

## Install (Ubuntu) — MANUAL PRODUCTION STEPS

Two-step: HTTP bootstrap for ACME, then the HTTPS site with HSTS.

```bash
sudo apt-get update
sudo apt-get install -y nginx
sudo cp /opt/onboard-ai/deploy/nginx/onboardai.aoe.kz.conf \
  /etc/nginx/sites-available/onboardai.aoe.kz
sudo ln -sf /etc/nginx/sites-available/onboardai.aoe.kz /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

HTTP smoke (Phase 1 — no certificate yet):

```bash
curl -I http://onboardai.aoe.kz
curl -fsS http://onboardai.aoe.kz/health
```

Then Certbot (Phase 2 — **do not run until DNS answers**):

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d onboardai.aoe.kz
sudo certbot renew --dry-run
```

Expected eventual certificate paths (created by Certbot, not this repo):

- `/etc/letsencrypt/live/onboardai.aoe.kz/fullchain.pem`
- `/etc/letsencrypt/live/onboardai.aoe.kz/privkey.pem`

Replace certbot's patched HTTP site with the HTTPS-only production config:

```bash
sudo cp /opt/onboard-ai/deploy/nginx/onboardai.aoe.kz.https.conf \
  /etc/nginx/sites-available/onboardai.aoe.kz
sudo nginx -t && sudo systemctl reload nginx
```

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

## Smoke (after HTTPS)

```bash
ss -lntp | egrep ':80|:443|:3000|:8000|:5432|:6379'
# :3000 must be 127.0.0.1 only; :80/:443 public; API/Postgres/Redis unpublished
curl -fsS https://onboardai.aoe.kz/health
curl -fsS https://onboardai.aoe.kz/ready
curl -fsSI https://onboardai.aoe.kz/login | tr -d '\r' | grep -i '^strict-transport-security'
curl -fsSI https://onboardai.aoe.kz/login | tr -d '\r' | grep -i '^set-cookie' || true
```
