from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.rls_guard import assert_rls_context

ModelT = TypeVar("ModelT", bound=Base)

_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 1000
_IMMUTABLE_FIELDS = frozenset({"id", "created_at"})


class BaseRepository(Generic[ModelT]):
    """Generic async CRUD repository.

    Does not commit transactions — the caller owns the unit of work.
    Requires an established UoW RLS mode (tenant/platform/auth/session).
    """

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self._session = session
        self._model = model

    def _ensure_rls_context(self) -> None:
        """Fail fast when UnitOfWork has not entered an RLS mode."""
        assert_rls_context(self._session)

    async def create(self, entity: ModelT) -> ModelT:
        self._ensure_rls_context()
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelT | None:
        self._ensure_rls_context()
        return await self._session.get(self._model, entity_id)

    async def list(self, *, offset: int = 0, limit: int = _DEFAULT_LIST_LIMIT) -> list[ModelT]:
        self._ensure_rls_context()
        stmt = self._list_statement(offset=offset, limit=limit)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def update(self, entity_id: uuid.UUID, **values: Any) -> ModelT | None:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return None

        for key, value in values.items():
            if key in _IMMUTABLE_FIELDS:
                raise ValueError(f"Field {key!r} cannot be updated")
            if not hasattr(entity, key):
                raise AttributeError(f"{self._model.__name__} has no attribute {key!r}")
            setattr(entity, key, value)

        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete(self, entity_id: uuid.UUID) -> bool:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return False

        await self._session.delete(entity)
        await self._session.flush()
        return True

    def _list_statement(self, *, offset: int, limit: int) -> Select[tuple[ModelT]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[ModelT]] = select(self._model)
        created_at = getattr(self._model, "created_at", None)
        if created_at is not None:
            stmt = stmt.order_by(created_at.desc())
        return stmt.offset(offset).limit(limit)
