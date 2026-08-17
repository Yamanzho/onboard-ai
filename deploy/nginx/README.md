# Host nginx TLS edge

Canonical cutover: [docs/deployment/https.md](../../docs/deployment/https.md).

Production topology:

```text
Internet → host nginx (:80, later :443 TLS) → 127.0.0.1:3000 (Compose frontend)
                                            → api:8000 (Docker internal only)
```

This directory ships **HTTP-first** (`onboardai.aoe.kz.conf`). It does **not**
reference Let's Encrypt certificate files. Those files do not exist until a
manual Certbot run on the VPS.

## Rules

1. Use `docker compose -f docker-compose.yml -f docker-compose.prod.yml` only.
2. **Never** stack `docker-compose.ip.yml` in production — it publishes `0.0.0.0:3000` and sets `AUTH_COOKIE_SECURE=false`.
3. Frontend must stay on `127.0.0.1:3000`.
4. Do not publish API `:8000`, Postgres, or Redis.
5. Do not proxy `/api` from host Nginx to `:8000`. Frontend nginx proxies `/api` → `api:8000` on the Compose network.

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

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

## Smoke (after HTTPS)

```bash
ss -lntp | egrep ':80|:443|:3000|:8000|:5432|:6379'
# :3000 must be 127.0.0.1 only; :80/:443 public; :8000/:5432/:6379 must not be public
curl -fsS https://onboardai.aoe.kz/health
curl -fsSI https://onboardai.aoe.kz/login | tr -d '\r' | grep -i '^set-cookie' || true
```
