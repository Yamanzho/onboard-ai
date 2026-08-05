#!/usr/bin/env python3
"""Idempotent demo tenant seed for local / Compose runtime.

Creates a fixed-UUID company plus admin, HR, and employee accounts so the
Admin Panel and Telegram bot can be exercised without manual bootstrapping.

Run (after migrations):

    python -m scripts.seed_demo
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID

# Allow `python scripts/seed_demo.py` from repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import get_settings
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.session import async_session_factory
from app.db.uow import UnitOfWork

logger = logging.getLogger("seed_demo")

# Stable IDs — documented in README / DEPLOYMENT.md
DEMO_COMPANY_ID = UUID("11111111-1111-4111-8111-111111111111")
DEMO_ADMIN_ID = UUID("22222222-2222-4222-8222-222222222222")
DEMO_HR_ID = UUID("33333333-3333-4333-8333-333333333333")
DEMO_EMPLOYEE_ID = UUID("44444444-4444-4444-8444-444444444444")

DEMO_COMPANY_SLUG = "demo"
DEMO_ADMIN_TELEGRAM = 100001
DEMO_HR_TELEGRAM = 100002
DEMO_EMPLOYEE_TELEGRAM = 100003


async def seed() -> None:
    settings = get_settings()
    async with UnitOfWork(session_factory=async_session_factory) as uow:
        company = await uow.companies.get_by_id(DEMO_COMPANY_ID)
        if company is None:
            company = await uow.companies.create(
                Company(
                    id=DEMO_COMPANY_ID,
                    name="Demo Company",
                    slug=DEMO_COMPANY_SLUG,
                    timezone="UTC",
                    is_active=True,
                    settings={"seed": "demo"},
                ),
            )
            logger.info("Created demo company %s", company.id)
        else:
            logger.info("Demo company already exists (%s)", company.id)

        await _ensure_employee(
            uow,
            employee_id=DEMO_ADMIN_ID,
            company_id=DEMO_COMPANY_ID,
            telegram_user_id=DEMO_ADMIN_TELEGRAM,
            full_name="Demo Admin",
            email="admin@demo.local",
            role=EmployeeRole.ADMIN.value,
        )
        await _ensure_employee(
            uow,
            employee_id=DEMO_HR_ID,
            company_id=DEMO_COMPANY_ID,
            telegram_user_id=DEMO_HR_TELEGRAM,
            full_name="Demo HR",
            email="hr@demo.local",
            role=EmployeeRole.HR.value,
        )
        await _ensure_employee(
            uow,
            employee_id=DEMO_EMPLOYEE_ID,
            company_id=DEMO_COMPANY_ID,
            telegram_user_id=DEMO_EMPLOYEE_TELEGRAM,
            full_name="Demo Employee",
            email="employee@demo.local",
            role=EmployeeRole.EMPLOYEE.value,
        )
        await uow.commit()

    print()
    print("=== Demo seed ready ===")
    print(f"Company ID (BOT_COMPANY_ID): {DEMO_COMPANY_ID}")
    print(f"Admin UUID (login):          {DEMO_ADMIN_ID}")
    print(f"HR UUID (login):             {DEMO_HR_ID}")
    print(f"Employee UUID:               {DEMO_EMPLOYEE_ID}")
    print(f"Password (AUTH_PASSWORD):    {settings.auth_password}")
    print(f"Employee telegram_user_id:   {DEMO_EMPLOYEE_TELEGRAM}")
    print("Admin panel: http://localhost:3000  (or :5173 in Vite mode)")
    print("API docs:    http://localhost:8000/docs")
    print()


async def _ensure_employee(
    uow: UnitOfWork,
    *,
    employee_id: UUID,
    company_id: UUID,
    telegram_user_id: int,
    full_name: str,
    email: str,
    role: str,
) -> None:
    existing = await uow.employees.get_by_id(employee_id)
    if existing is not None:
        logger.info("Employee %s already exists (%s)", role, employee_id)
        return
    await uow.employees.create(
        Employee(
            id=employee_id,
            company_id=company_id,
            telegram_user_id=telegram_user_id,
            full_name=full_name,
            email=email,
            role=role,
            status=EmployeeStatus.ACTIVE.value,
        ),
    )
    logger.info("Created %s employee %s", role, employee_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(seed())


if __name__ == "__main__":
    main()
