from fastapi import FastAPI

from app.api.exception_handlers import register_exception_handlers
from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=(
        "OnboardAI — Telegram-first SaaS for AI-powered employee onboarding.\n\n"
        "Authenticate via **Auth** (`/api/v1/auth/login`) using employee UUID + "
        "`AUTH_PASSWORD`, then click **Authorize** in Swagger.\n\n"
        "The Telegram bot uses `POST /api/v1/auth/bot/telegram` with "
        "`X-Bot-Service-Token` to exchange a Telegram user id for a normal "
        "employee JWT (no `AUTH_PASSWORD`).\n\n"
        "Resource endpoints require a Bearer access token. Roles: "
        "**admin** (companies), **admin/hr** (employees, programs, steps, assignments), "
        "**employee** (own assignments/progress; HR/admin may view any within tenant).\n\n"
        "All data access is **tenant-scoped** to `current_user.company_id`. "
        "Cross-tenant UUIDs return **404**."
    ),
    version="0.1.0",
    debug=settings.debug,
    openapi_tags=[
        {
            "name": "Auth",
            "description": "JWT login, refresh, and current-user profile.",
        },
        {
            "name": "Companies",
            "description": "Manage company tenants (create, read, update, delete).",
        },
        {
            "name": "Employees",
            "description": "Manage employees within a company tenant.",
        },
        {
            "name": "Programs",
            "description": "Onboarding program lifecycle: draft, publish, archive.",
        },
        {
            "name": "Steps",
            "description": "Ordered steps within an onboarding program.",
        },
        {
            "name": "Assignments",
            "description": "Assign published programs to employees and cancel assignments.",
        },
        {
            "name": "Progress",
            "description": "Track and complete per-step progress for an assignment.",
        },
        {
            "name": "Knowledge",
            "description": (
                "Company knowledge base: articles (versioned), categories, and tags."
            ),
        },
        {
            "name": "Super Admin",
            "description": (
                "Platform Super Admin panel: cross-tenant companies, users, "
                "dashboard stats, and global settings. Separate auth "
                "(email + password); tokens have no company_id."
            ),
        },
    ],
)

register_exception_handlers(app)
app.include_router(api_v1_router)


@app.get("/health", tags=["Health"], summary="Health check")
async def health() -> dict[str, str]:
    """Return service liveness status."""
    return {"status": "ok"}
