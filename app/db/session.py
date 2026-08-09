from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


# Intentionally no FastAPI ``get_session`` dependency.
# All request/DB access must go through ``UnitOfWork`` + ``enter_tenant`` /
# ``enter_platform`` / ``enter_auth_bootstrap`` / ``enter_session_bootstrap``
# so RLS GUCs cannot be skipped by a generic session injection (F-10).
