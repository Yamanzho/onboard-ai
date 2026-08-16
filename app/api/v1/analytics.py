from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import HRUser
from app.api.deps import get_analytics_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.analytics import OnboardingAnalyticsResponse
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])

AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin or HR role required"},
}


@router.get(
    "/onboarding",
    response_model=OnboardingAnalyticsResponse,
    summary="Onboarding analytics",
    description=(
        "Tenant-scoped onboarding metrics derived from employees, assignments, "
        "and progress. Employees cannot access this endpoint."
    ),
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def get_onboarding_analytics(
    current_user: HRUser,
    service: AnalyticsServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
) -> OnboardingAnalyticsResponse:
    return await service.get_onboarding_analytics(
        company_id,
        actor_company_id=current_user.company_id,
    )
