from __future__ import annotations

from enum import Enum
from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.rls_guard import SESSION_RLS_MODE_KEY, install_rls_orm_guard
from app.db.session import async_session_factory
from app.repositories.ai_conversation import AIConversationRepository
from app.repositories.assignment import AssignmentRepository
from app.repositories.company import CompanyRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.knowledge_article import KnowledgeArticleRepository
from app.repositories.knowledge_article_link import KnowledgeArticleLinkRepository
from app.repositories.knowledge_article_version import KnowledgeArticleVersionRepository
from app.repositories.knowledge_category import KnowledgeCategoryRepository
from app.repositories.knowledge_tag import KnowledgeTagRepository
from app.repositories.company_subscription import CompanySubscriptionRepository
from app.repositories.employee_invite import EmployeeInviteRepository
from app.repositories.onboarding_program import OnboardingProgramRepository
from app.repositories.platform_audit_log import PlatformAuditLogRepository
from app.repositories.progress import ProgressRepository
from app.repositories.refresh_session import RefreshSessionRepository
from app.repositories.step import StepRepository
from app.repositories.subscription_history import SubscriptionHistoryRepository
from app.repositories.super_admin import SuperAdminRepository


class RlsMode(str, Enum):
    """Transaction-scoped PostgreSQL RLS context mode."""

    NONE = "none"
    TENANT = "tenant"
    PLATFORM = "platform"
    AUTH_BOOTSTRAP = "auth_bootstrap"
    SESSION_BOOTSTRAP = "session_bootstrap"


class UnitOfWork:
    """Async Unit of Work over a single ``AsyncSession``.

    Owns transaction boundaries (``commit`` / ``rollback``) and exposes one
    repository instance per aggregate root, all sharing the same session.

    SEC-R3: every UoW must call ``enter_tenant`` / ``enter_platform`` /
    ``enter_auth_bootstrap`` / ``enter_session_bootstrap`` before repository
    queries. Context uses transaction-local ``set_config(..., true)`` only.
    """

    session: AsyncSession
    companies: CompanyRepository
    employees: EmployeeRepository
    onboarding_programs: OnboardingProgramRepository
    steps: StepRepository
    assignments: AssignmentRepository
    progress: ProgressRepository
    knowledge_categories: KnowledgeCategoryRepository
    knowledge_tags: KnowledgeTagRepository
    knowledge_articles: KnowledgeArticleRepository
    knowledge_article_versions: KnowledgeArticleVersionRepository
    knowledge_article_links: KnowledgeArticleLinkRepository
    ai_conversations: AIConversationRepository
    super_admins: SuperAdminRepository
    company_subscriptions: CompanySubscriptionRepository
    subscription_history: SubscriptionHistoryRepository
    employee_invites: EmployeeInviteRepository
    platform_audit_logs: PlatformAuditLogRepository
    refresh_sessions: RefreshSessionRepository

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory or async_session_factory
        self._session: AsyncSession | None = None
        self._rls_mode: RlsMode = RlsMode.NONE
        self._tenant_company_id: UUID | None = None
        self._auth_employee_id: UUID | None = None
        self._auth_telegram_user_id: int | None = None
        self._auth_invite_token_hash: str | None = None
        self._auth_super_admin_id: UUID | None = None
        self._auth_super_admin_email: str | None = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.session = self._session
        install_rls_orm_guard(self._session)
        self.companies = CompanyRepository(self._session)
        self.employees = EmployeeRepository(self._session)
        self.onboarding_programs = OnboardingProgramRepository(self._session)
        self.steps = StepRepository(self._session)
        self.assignments = AssignmentRepository(self._session)
        self.progress = ProgressRepository(self._session)
        self.knowledge_categories = KnowledgeCategoryRepository(self._session)
        self.knowledge_tags = KnowledgeTagRepository(self._session)
        self.knowledge_articles = KnowledgeArticleRepository(self._session)
        self.knowledge_article_versions = KnowledgeArticleVersionRepository(self._session)
        self.knowledge_article_links = KnowledgeArticleLinkRepository(self._session)
        self.ai_conversations = AIConversationRepository(self._session)
        self.super_admins = SuperAdminRepository(self._session)
        self.company_subscriptions = CompanySubscriptionRepository(self._session)
        self.subscription_history = SubscriptionHistoryRepository(self._session)
        self.employee_invites = EmployeeInviteRepository(self._session)
        self.platform_audit_logs = PlatformAuditLogRepository(self._session)
        self.refresh_sessions = RefreshSessionRepository(self._session)
        self._rls_mode = RlsMode.NONE
        self._tenant_company_id = None
        self._clear_auth_pins()
        self._session.info[SESSION_RLS_MODE_KEY] = RlsMode.NONE
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None and self._session is not None:
                await self._session.rollback()
        finally:
            if self._session is not None:
                # close() rolls back any still-open transaction and detaches
                # instances without expiring already-loaded attributes.
                self._session.info[SESSION_RLS_MODE_KEY] = RlsMode.NONE
                await self._session.close()
            self._session = None
            self._rls_mode = RlsMode.NONE
            self._tenant_company_id = None
            self._clear_auth_pins()

    @property
    def rls_mode(self) -> RlsMode:
        return self._rls_mode

    def require_rls_context(self, *allowed: RlsMode) -> None:
        """Fail closed in application code when the UoW mode is wrong/missing."""
        if self._rls_mode is RlsMode.NONE:
            raise RuntimeError(
                "RLS context not established; call enter_tenant/enter_platform/"
                "enter_auth_bootstrap/enter_session_bootstrap before DB access"
            )
        if allowed and self._rls_mode not in allowed:
            raise RuntimeError(
                f"RLS mode {self._rls_mode.value!r} not allowed; "
                f"expected one of {[m.value for m in allowed]}"
            )

    async def enter_tenant(self, company_id: UUID) -> None:
        """Bind this transaction to one tenant (DB-resolved company_id only)."""
        if not isinstance(company_id, UUID):
            raise TypeError("company_id must be a UUID")
        self._tenant_company_id = company_id
        self._clear_auth_pins()
        self._rls_mode = RlsMode.TENANT
        self._sync_session_rls_mode()
        await self._apply_rls_gucs()

    async def enter_platform(self) -> None:
        """Enable Super Admin / platform cross-tenant access for this transaction."""
        self._tenant_company_id = None
        self._clear_auth_pins()
        self._rls_mode = RlsMode.PLATFORM
        self._sync_session_rls_mode()
        await self._apply_rls_gucs()

    async def enter_auth_bootstrap(
        self,
        *,
        employee_id: UUID | None = None,
        telegram_user_id: int | None = None,
        invite_token_hash: str | None = None,
        super_admin_id: UUID | None = None,
        super_admin_email: str | None = None,
    ) -> None:
        """Auth/subject resolution (login, invite token, JWT / Super Admin load).

        Pins are transaction-local GUCs (never client-controlled HTTP fields):
        - ``employee_id`` — SELECT/UPDATE one employees row
        - ``telegram_user_id`` — SELECT employees rows with that Telegram id
        - ``invite_token_hash`` — SELECT/UPDATE one employee_invites row by hash
        - ``super_admin_id`` / ``super_admin_email`` — SELECT one super_admins row

        After invite accept, re-enter with ``employee_id`` so sibling unused invites
        for that employee can be invalidated without a broad auth UPDATE policy.
        """
        if employee_id is not None and not isinstance(employee_id, UUID):
            raise TypeError("employee_id must be a UUID")
        if telegram_user_id is not None:
            if not isinstance(telegram_user_id, int) or isinstance(
                telegram_user_id, bool
            ):
                raise TypeError("telegram_user_id must be an int")
            if telegram_user_id <= 0:
                raise ValueError("telegram_user_id must be a positive integer")
        if super_admin_id is not None and not isinstance(super_admin_id, UUID):
            raise TypeError("super_admin_id must be a UUID")
        if invite_token_hash is not None:
            if not isinstance(invite_token_hash, str) or not invite_token_hash.strip():
                raise ValueError("invite_token_hash must be a non-empty string")
            invite_token_hash = invite_token_hash.strip()
        if super_admin_email is not None:
            if not isinstance(super_admin_email, str) or not super_admin_email.strip():
                raise ValueError("super_admin_email must be a non-empty string")
            super_admin_email = super_admin_email.strip().lower()

        self._tenant_company_id = None
        self._auth_employee_id = employee_id
        self._auth_telegram_user_id = telegram_user_id
        self._auth_invite_token_hash = invite_token_hash
        self._auth_super_admin_id = super_admin_id
        self._auth_super_admin_email = super_admin_email
        self._rls_mode = RlsMode.AUTH_BOOTSTRAP
        self._sync_session_rls_mode()
        await self._apply_rls_gucs()

    async def enter_session_bootstrap(self) -> None:
        """Refresh-session issue/rotate/revoke only."""
        self._tenant_company_id = None
        self._clear_auth_pins()
        self._rls_mode = RlsMode.SESSION_BOOTSTRAP
        self._sync_session_rls_mode()
        await self._apply_rls_gucs()

    def _clear_auth_pins(self) -> None:
        self._auth_employee_id = None
        self._auth_telegram_user_id = None
        self._auth_invite_token_hash = None
        self._auth_super_admin_id = None
        self._auth_super_admin_email = None

    async def commit(self) -> None:
        session = self._ensure_session()
        await session.commit()
        # commit ends the transaction — LOCAL GUCs are gone; re-apply if callers
        # continue using this UoW (e.g. reload after commit).
        if self._rls_mode is not RlsMode.NONE:
            self._sync_session_rls_mode()
            await self._apply_rls_gucs()

    async def rollback(self) -> None:
        session = self._ensure_session()
        await session.rollback()
        if self._rls_mode is not RlsMode.NONE:
            self._sync_session_rls_mode()
            await self._apply_rls_gucs()

    def _ensure_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork is not active; use 'async with UnitOfWork()'")
        return self._session

    def _sync_session_rls_mode(self) -> None:
        """Publish mode to session.info before any ORM execute (incl. set_config)."""
        session = self._ensure_session()
        session.info[SESSION_RLS_MODE_KEY] = self._rls_mode

    async def _apply_rls_gucs(self) -> None:
        """Apply transaction-local GUCs (set_config third arg = true → LOCAL)."""
        session = self._ensure_session()
        if not session.in_transaction():
            await session.begin()

        company = str(self._tenant_company_id) if self._tenant_company_id else ""
        platform = "on" if self._rls_mode is RlsMode.PLATFORM else ""
        auth = "bootstrap" if self._rls_mode is RlsMode.AUTH_BOOTSTRAP else ""
        session_mode = "bootstrap" if self._rls_mode is RlsMode.SESSION_BOOTSTRAP else ""
        auth_employee = (
            str(self._auth_employee_id) if self._auth_employee_id is not None else ""
        )
        auth_telegram = (
            str(self._auth_telegram_user_id)
            if self._auth_telegram_user_id is not None
            else ""
        )
        invite_hash = self._auth_invite_token_hash or ""
        sa_id = (
            str(self._auth_super_admin_id)
            if self._auth_super_admin_id is not None
            else ""
        )
        sa_email = self._auth_super_admin_email or ""

        # Always set all GUCs so a mode switch cannot leave stale LOCAL values
        # within the same transaction.
        await session.execute(
            text("SELECT set_config('app.current_company_id', :v, true)"),
            {"v": company},
        )
        await session.execute(
            text("SELECT set_config('app.platform_admin', :v, true)"),
            {"v": platform},
        )
        await session.execute(
            text("SELECT set_config('app.auth_mode', :v, true)"),
            {"v": auth},
        )
        await session.execute(
            text("SELECT set_config('app.session_mode', :v, true)"),
            {"v": session_mode},
        )
        await session.execute(
            text("SELECT set_config('app.auth_employee_id', :v, true)"),
            {"v": auth_employee},
        )
        await session.execute(
            text("SELECT set_config('app.auth_telegram_user_id', :v, true)"),
            {"v": auth_telegram},
        )
        await session.execute(
            text("SELECT set_config('app.auth_invite_token_hash', :v, true)"),
            {"v": invite_hash},
        )
        await session.execute(
            text("SELECT set_config('app.auth_super_admin_id', :v, true)"),
            {"v": sa_id},
        )
        await session.execute(
            text("SELECT set_config('app.auth_super_admin_email', :v, true)"),
            {"v": sa_email},
        )
