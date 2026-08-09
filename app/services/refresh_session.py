from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token, hash_token
from app.db.models.refresh_session import RefreshSession
from app.db.uow import UnitOfWork
from app.schemas.auth import TokenResponse

SUBJECT_EMPLOYEE = "employee"
SUBJECT_SUPER_ADMIN = "super_admin"


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    tokens: TokenResponse
    session: RefreshSession


class RefreshSessionService:
    """Issue and rotate refresh sessions with reuse detection."""

    async def issue(
        self,
        *,
        subject_type: str,
        subject_id: UUID,
        role: str,
        company_id: UUID | None,
        family_id: UUID | None = None,
    ) -> IssuedTokens:
        settings = get_settings()
        raw_refresh = secrets.token_urlsafe(48)
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
        family = family_id or uuid4()
        session = RefreshSession(
            token_hash=hash_token(raw_refresh),
            family_id=family,
            subject_type=subject_type,
            subject_id=subject_id,
            expires_at=expires_at,
        )
        async with UnitOfWork() as uow:
            await uow.enter_session_bootstrap()
            await uow.refresh_sessions.create(session)
            await uow.commit()

        tokens = TokenResponse(
            access_token=create_access_token(
                subject=subject_id,
                role=role,
                company_id=company_id,
            ),
            refresh_token=raw_refresh,
            token_type="bearer",
        )
        return IssuedTokens(tokens=tokens, session=session)

    async def begin_rotation(
        self,
        *,
        raw_refresh: str,
        subject_type: str,
    ) -> tuple[UUID, UUID]:
        """Validate and revoke the presented refresh token.

        Returns ``(subject_id, family_id)`` for issuing the replacement.
        Reuse of a revoked token kills the whole family.
        """
        token_hash = hash_token(raw_refresh)
        async with UnitOfWork() as uow:
            await uow.enter_session_bootstrap()
            existing = await uow.refresh_sessions.get_by_token_hash_for_update(token_hash)
            if existing is None or existing.subject_type != subject_type:
                raise UnauthorizedError("Invalid refresh token")

            if existing.revoked_at is not None:
                await uow.refresh_sessions.revoke_family(existing.family_id)
                await uow.commit()
                raise UnauthorizedError("Refresh token reuse detected")

            if existing.expires_at <= datetime.now(UTC):
                existing.revoked_at = datetime.now(UTC)
                await uow.commit()
                raise UnauthorizedError("Invalid refresh token")

            existing.revoked_at = datetime.now(UTC)
            subject_id = existing.subject_id
            family_id = existing.family_id
            await uow.commit()
            return subject_id, family_id

    async def revoke_raw(self, raw_refresh: str | None) -> None:
        if not raw_refresh:
            return
        async with UnitOfWork() as uow:
            await uow.enter_session_bootstrap()
            await uow.refresh_sessions.revoke_by_token_hash(hash_token(raw_refresh))
            await uow.commit()

    async def revoke_all_for_subject(
        self,
        *,
        subject_type: str,
        subject_id: UUID,
    ) -> int:
        """Revoke every active refresh session for one subject (logout-all / lockout)."""
        async with UnitOfWork() as uow:
            await uow.enter_session_bootstrap()
            count = await uow.refresh_sessions.revoke_all_for_subject(
                subject_type=subject_type,
                subject_id=subject_id,
            )
            await uow.commit()
            return count
