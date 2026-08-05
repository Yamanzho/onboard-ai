from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from app.repositories.step import StepRepository
from app.repositories.subscription_history import SubscriptionHistoryRepository
from app.repositories.super_admin import SuperAdminRepository


class UnitOfWork:
    """Async Unit of Work over a single ``AsyncSession``.

    Owns transaction boundaries (``commit`` / ``rollback``) and exposes one
    repository instance per aggregate root, all sharing the same session.

    Repositories never commit — call ``await uow.commit()`` explicitly.
    On context exit, uncommitted work is rolled back and the session is closed.
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

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory or async_session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.session = self._session
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
                await self._session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._ensure_session()
        await session.commit()

    async def rollback(self) -> None:
        session = self._ensure_session()
        await session.rollback()

    def _ensure_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork is not active; use 'async with UnitOfWork()'")
        return self._session
