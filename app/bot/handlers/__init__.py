from aiogram import Router

from app.bot.handlers.onboarding import router as onboarding_router
from app.bot.handlers.start import router as start_router

_handlers_router: Router | None = None


def get_handlers_router() -> Router:
    global _handlers_router
    if _handlers_router is None:
        root = Router(name="bot_handlers")
        root.include_router(start_router)
        root.include_router(onboarding_router)
        _handlers_router = root
    return _handlers_router
