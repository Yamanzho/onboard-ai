# Host nginx TLS edge

Production topology:

```text
Internet → host nginx (:443 TLS) → 127.0.0.1:3000 (Compose frontend)
                                 → api:8000 (Docker internal only)
```

## Rules

1. Use `docker compose -f docker-compose.yml -f docker-compose.prod.yml` only.
2. **Never** stack `docker-compose.ip.yml` in production — it publishes `0.0.0.0:3000` and sets `AUTH_COOKIE_SECURE=false`.
3. Frontend must stay on `127.0.0.1:3000`.
4. Do not publish API `:8000`, Postgres, or Redis.

## DNS prerequisite

`onboardai.aoe.kz` must resolve to the VPS public IP before `certbot` can issue a certificate. Do not pretend DNS exists.

## Install (Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo cp /opt/onboard-ai/deploy/nginx/onboardai.aoe.kz.conf \
  /etc/nginx/sites-available/onboardai.aoe.kz
sudo ln -sf /etc/nginx/sites-available/onboardai.aoe.kz /etc/nginx/sites-enabled/
# Temporarily comment ssl_* lines OR use certbot --nginx which patches them.
sudo certbot --nginx -d onboardai.aoe.kz
sudo nginx -t && sudo systemctl reload nginx
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

## Smoke

```bash
ss -lntp | egrep ':80|:443|:3000'
# :3000 must be 127.0.0.1 only; :80/:443 public
curl -fsS https://onboardai.aoe.kz/health
curl -fsSI https://onboardai.aoe.kz/login | tr -d '\r' | grep -i '^set-cookie' || true
```
