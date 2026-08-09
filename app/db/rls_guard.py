"""Application-level RLS context fail-fast (SEC-R3 Finding 2).

PostgreSQL RLS remains the security boundary. This guard only ensures a
UnitOfWork established one of the four allowed modes before repository
ORM access, so missing context fails loudly instead of silently empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SESSION_RLS_MODE_KEY = "rls_mode"
_SESSION_RLS_GUARD_KEY = "_rls_orm_guard_installed"


def _normalize_mode(raw: object) -> str:
    from app.db.uow import RlsMode

    if raw is None:
        return RlsMode.NONE.value
    if isinstance(raw, RlsMode):
        return raw.value
    return str(raw)


def assert_rls_context(session: AsyncSession | Session) -> None:
    """Raise if the session has no established RLS mode."""
    from app.db.uow import RlsMode

    info = session.info if hasattr(session, "info") else {}
    mode = _normalize_mode(info.get(SESSION_RLS_MODE_KEY, RlsMode.NONE))
    if mode == RlsMode.NONE.value:
        raise RuntimeError(
            "RLS context not established; call enter_tenant/enter_platform/"
            "enter_auth_bootstrap/enter_session_bootstrap before DB access"
        )


def install_rls_orm_guard(session: AsyncSession) -> None:
    """Install a once-per-session ORM execute guard on the sync session."""
    if session.info.get(_SESSION_RLS_GUARD_KEY):
        return
    session.info[_SESSION_RLS_GUARD_KEY] = True
    from app.db.uow import RlsMode

    session.info[SESSION_RLS_MODE_KEY] = RlsMode.NONE

    sync_session = session.sync_session

    @event.listens_for(sync_session, "do_orm_execute")
    def _guard_orm_execute(orm_execute_state: object) -> None:  # noqa: ARG001
        # Mode must be set on session.info *before* set_config in enter_*.
        mode = _normalize_mode(session.info.get(SESSION_RLS_MODE_KEY, RlsMode.NONE))
        if mode == RlsMode.NONE.value:
            raise RuntimeError(
                "RLS context not established; call enter_tenant/enter_platform/"
                "enter_auth_bootstrap/enter_session_bootstrap before DB access"
            )
