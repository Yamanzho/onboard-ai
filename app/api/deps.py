from functools import lru_cache

from app.services.assignment import AssignmentService
from app.services.company import CompanyService
from app.services.employee import EmployeeService
from app.services.knowledge.article_service import ArticleService
from app.services.knowledge.category_service import CategoryService
from app.services.knowledge.tag_service import TagService
from app.services.onboarding_program import OnboardingProgramService
from app.services.platform import PlatformService, SuperAdminAuthService
from app.services.progress import ProgressService
from app.services.step import StepService


@lru_cache
def get_company_service() -> CompanyService:
    """Provide a shared CompanyService instance for request handlers."""
    return CompanyService()


@lru_cache
def get_employee_service() -> EmployeeService:
    return EmployeeService()


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
def get_article_service() -> ArticleService:
    return ArticleService()


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
