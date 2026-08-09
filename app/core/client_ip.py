"""Resolve client IP for rate limiting (optional trusted proxy headers)."""

from __future__ import annotations

from fastapi import Request

from app.core.config import get_settings


def client_ip(request: Request) -> str:
    """Return the client IP used for login / refresh / invite / bot rate limits.

    When ``TRUST_PROXY_HEADERS`` is false (default), proxy headers are ignored
    and ``request.client.host`` is used.

    When trust is enabled (production behind the frontend nginx), prefer
    ``X-Real-IP`` then ``X-Forwarded-For``. The trusted single-proxy deployment
    **must overwrite** both headers with ``$remote_addr`` (see
    ``frontend/nginx.prod.conf``) — never append client-supplied XFF via
    ``$proxy_add_x_forwarded_for``. Preferring ``X-Real-IP`` ensures a spoofed
    ``X-Forwarded-For`` alone cannot open a fresh rate-limit bucket when the
    proxy sets the real peer address correctly.

    Enable trust only when the API is not reachable directly from the public
    internet.
    """
    settings = get_settings()
    if settings.trust_proxy_headers:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # After nginx overwrite this is a single $remote_addr value.
            # If a comma-chain still appears (misconfigured append proxy),
            # use the rightmost hop (immediate peer) — not the client-controlled
            # leftmost address.
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            if parts:
                return parts[-1]
    if request.client is not None:
        return request.client.host
    return "unknown"
