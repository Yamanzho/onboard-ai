from fastapi import FastAPI

from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import RequestIdMiddleware
from app.api.v1.router import router as api_v1_router
from app.core.config import Settings, get_settings
from app.core.readiness import assert_ready


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Production (``APP_ENV=production``) disables public OpenAPI/Swagger/ReDoc
    surfaces (``docs_url`` / ``redoc_url`` / ``openapi_url`` set to ``None``).
    """
    settings = settings or get_settings()
    docs_enabled = not settings.is_production

    application = FastAPI(
        title=settings.app_name,
        description=(
            "OnboardAI — Telegram-first SaaS for AI-powered employee onboarding.\n\n"
            "Authenticate via **Auth** (`/api/v1/auth/login`) using employee **email** + "
            "password (legacy employee UUID still accepted), "
            "then click **Authorize** in Swagger.\n\n"
            "The Telegram bot uses `POST /api/v1/auth/bot/telegram` with "
            "`X-Bot-Service-Token` to exchange a Telegram user id for a normal "
            "employee JWT (no `AUTH_PASSWORD`).\n\n"
            "Resource endpoints require a Bearer access token. Roles: "
            "**admin** (own company profile), **admin/hr** (employees, programs, steps, "
            "assignments), **employee** (own assignments/progress; HR/admin may view any "
            "within tenant). Tenant **creation/deletion** is Super Admin only.\n\n"
            "All data access is **tenant-scoped** to `current_user.company_id`. "
            "Cross-tenant UUIDs return **404**."
        ),
        version="0.1.0",
        debug=settings.debug,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        openapi_tags=[
            {
                "name": "Auth",
                "description": "JWT login, refresh, and current-user profile.",
            },
            {
                "name": "Companies",
                "description": (
                    "Tenant-scoped company profile (read/update own company). "
                    "Creating, deleting, and activating tenants is Super Admin only "
                    "via /api/v1/super-admin/companies."
                ),
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
                "name": "AI",
                "description": (
                    "Stateless tenant-scoped knowledge-base chat. "
                    "Identity comes from the authenticated session."
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

    register_exception_handlers(application)
    application.add_middleware(RequestIdMiddleware)
    application.include_router(api_v1_router)

    @application.get("/health", tags=["Health"], summary="Health check")
    async def health() -> dict[str, str]:
        """Return process liveness. Does not check PostgreSQL or Redis."""
        return {"status": "ok"}

    @application.get("/ready", tags=["Health"], summary="Readiness check")
    async def ready() -> dict[str, str]:
        """Return whether the app can accept traffic.

        Always checks PostgreSQL. Checks Redis when ``APP_ENV=production``
        (Redis is a required runtime dependency). Response bodies never
        include connection strings or secrets.
        """
        await assert_ready()
        return {"status": "ready"}

    return application


app = create_app()
