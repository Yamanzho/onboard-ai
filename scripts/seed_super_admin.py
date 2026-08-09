#!/usr/bin/env python3
"""Idempotent bootstrap of the platform Super Admin account.

Reads SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD / SUPER_ADMIN_FULL_NAME from env.

Run (after migrations):

    python -m scripts.seed_super_admin
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.services.platform import SuperAdminAuthService  # noqa: E402

logger = logging.getLogger("seed_super_admin")


async def seed() -> None:
    settings = get_settings()
    service = SuperAdminAuthService()
    admin = await service.ensure_bootstrap_admin(
        email=settings.super_admin_email,
        password=settings.super_admin_password,
        full_name=settings.super_admin_full_name,
    )
    print()
    print("=== Super Admin seed ready ===")
    print(f"Email:    {admin.email}")
    print("Password: (from SUPER_ADMIN_PASSWORD — not printed)")
    print(f"ID:       {admin.id}")
    print("Login:    POST /api/v1/super-admin/auth/login")
    print("Panel:    http://localhost:3000/super-admin/login")
    print()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(seed())


if __name__ == "__main__":
    main()
