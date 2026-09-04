from functools import lru_cache

from app.services.ai.chat import AIChatService
from app.services.ai.conversations import ConversationService
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.analytics import AnalyticsService
from app.services.assignment import AssignmentService
from app.services.company import CompanyService
from app.services.company_audit import CompanyAuditService
from app.services.department import DepartmentService
from app.services.employee import EmployeeService
from app.services.idempotency import IdempotencyService
from app.services.knowledge.article_service import ArticleService
from app.services.knowledge.category_service import CategoryService
from app.services.knowledge.tag_service import TagService
from app.services.onboarding_program import OnboardingProgramService
from app.services.platform import PlatformService, SuperAdminAuthService
from app.services.progress import ProgressService
from app.services.question_topic import QuestionTopicService
from app.services.responsibility import ResponsibilityLookupService
from app.services.step import StepService
from app.services.telegram_outbound import TelegramOutboundService


@lru_cache
def get_company_service() -> CompanyService:
    """Provide a shared CompanyService instance for request handlers."""
    return CompanyService()


@lru_cache
def get_company_audit_service() -> CompanyAuditService:
    return CompanyAuditService()


@lru_cache
def get_analytics_service() -> AnalyticsService:
    return AnalyticsService()


@lru_cache
def get_employee_service() -> EmployeeService:
    return EmployeeService()


@lru_cache
def get_department_service() -> DepartmentService:
    return DepartmentService()


@lru_cache
def get_question_topic_service() -> QuestionTopicService:
    return QuestionTopicService()


@lru_cache
def get_responsibility_lookup_service() -> ResponsibilityLookupService:
    return ResponsibilityLookupService()


@lru_cache
def get_onboarding_program_service() -> OnboardingProgramService:
    return OnboardingProgramService()


@lru_cache
def get_step_service() -> StepService:
    return StepService()


@lru_cache
def get_assignment_service() -> AssignmentService:
    return AssignmentService()


@lru_cache
def get_progress_service() -> ProgressService:
    return ProgressService()


@lru_cache
def get_chunk_indexer() -> KnowledgeChunkIndexer:
    return KnowledgeChunkIndexer()


@lru_cache
def get_ai_chat_service() -> AIChatService:
    return AIChatService()


@lru_cache
def get_idempotency_service() -> IdempotencyService:
    return IdempotencyService()


@lru_cache
def get_telegram_outbound_service() -> TelegramOutboundService:
    return TelegramOutboundService()


@lru_cache
def get_conversation_service() -> ConversationService:
    return ConversationService()


@lru_cache
def get_article_service() -> ArticleService:
    return ArticleService(chunk_indexer=get_chunk_indexer())


@lru_cache
def get_category_service() -> CategoryService:
    return CategoryService()


@lru_cache
def get_tag_service() -> TagService:
    return TagService()


@lru_cache
def get_super_admin_auth_service() -> SuperAdminAuthService:
    return SuperAdminAuthService()


@lru_cache
def get_platform_service() -> PlatformService:
    return PlatformService()
