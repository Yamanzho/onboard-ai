# Host nginx TLS edge

Production topology:

```text
Internet
  → host nginx (:443 TLS, HTTP→HTTPS)
    → 127.0.0.1:3000 (Compose frontend / nginx.prod.conf)
      → api:8000 (Docker internal only)
    → 127.0.0.1:8081 (bot webhook)
```

PostgreSQL and Redis stay on the Compose network (no host ports in production).

## Rules

1. Use `docker compose -f docker-compose.yml -f docker-compose.prod.yml` only.
2. **Never** stack `docker-compose.ip.yml` in production — it publishes `0.0.0.0:3000` and sets `AUTH_COOKIE_SECURE=false`.
3. Frontend must stay on `127.0.0.1:3000`.
4. Do not publish API `:8000`, Postgres, or Redis.
5. Enable `TRUST_PROXY_HEADERS=true` only with this unpublished-API topology. The edge **overwrites** `X-Real-IP` / `X-Forwarded-For` with `$remote_addr` (never `$proxy_add_x_forwarded_for`).
6. Enable HSTS only on the HTTPS site (`onboardai.aoe.kz.https.conf`) after HTTP redirects to HTTPS.

## DNS prerequisite

`onboardai.aoe.kz` must resolve to the VPS public IP before `certbot` can issue a certificate. Do not pretend DNS exists.

## Install (Ubuntu)

Two-step: HTTP bootstrap for ACME, then the HTTPS site with HSTS.

```bash
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo cp /opt/onboard-ai/deploy/nginx/onboardai.aoe.kz.conf \
  /etc/nginx/sites-available/onboardai.aoe.kz
sudo ln -sf /etc/nginx/sites-available/onboardai.aoe.kz /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d onboardai.aoe.kz
# Replace certbot's patched HTTP site with the HTTPS-only production config:
sudo cp /opt/onboard-ai/deploy/nginx/onboardai.aoe.kz.https.conf \
  /etc/nginx/sites-available/onboardai.aoe.kz
sudo nginx -t && sudo systemctl reload nginx
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

## Smoke

```bash
ss -lntp | egrep ':80|:443|:3000|:8000|:5432|:6379'
# :3000 must be 127.0.0.1 only; :80/:443 public; API/Postgres/Redis unpublished
curl -fsS https://onboardai.aoe.kz/health
curl -fsS https://onboardai.aoe.kz/ready
curl -fsSI https://onboardai.aoe.kz/login | tr -d '\r' | grep -i '^strict-transport-security'
curl -fsSI https://onboardai.aoe.kz/login | tr -d '\r' | grep -i '^set-cookie' || true
```
