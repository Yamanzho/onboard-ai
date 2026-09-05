from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import AnalyticsViewUser
from app.api.deps import get_analytics_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.analytics import AssignmentAnalyticsResponse, OnboardingAnalyticsResponse
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])

AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": (
            "analytics.view required. Own-only visibility is forbidden. "
            "Department-scoped callers receive department aggregates only."
        )
    },
}


@router.get(
    "/onboarding",
    response_model=OnboardingAnalyticsResponse,
    summary="Onboarding analytics",
    description=(
        "Tenant-scoped onboarding metrics derived from employees, assignments, "
        "and progress. Requires analytics.view. Department-scoped callers only "
        "see their department. Own-only callers receive 403."
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
    current_user: AnalyticsViewUser,
    service: AnalyticsServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    department_id: Annotated[
        UUID | None,
        Query(description="Optional department filter (all-scope callers only)"),
    ] = None,
) -> OnboardingAnalyticsResponse:
    return await service.get_onboarding_analytics(
        company_id,
        actor_company_id=current_user.company_id,
        actor=current_user,
        department_id=department_id,
    )


@router.get(
    "/assignments",
    response_model=AssignmentAnalyticsResponse,
    summary="Assignment operational analytics",
    description=(
        "SQL-aggregated assignment counts for the caller's allowed scope.\n\n"
        "completion_rate = completed / (completed + pending + in_progress) "
        "as a 0-100 percent. Cancelled assignments are excluded.\n\n"
        "Department-scoped callers always receive their department numbers "
        "(requested department_id outside that department is 403). "
        "All-scope callers may pass optional department_id / assignment_type. "
        "Own-only callers are forbidden — this is a management endpoint."
    ),
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: ERROR_RESPONSES[status.HTTP_400_BAD_REQUEST],
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def get_assignment_analytics(
    current_user: AnalyticsViewUser,
    service: AnalyticsServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    department_id: Annotated[
        UUID | None,
        Query(description="Optional department filter (all-scope callers only)"),
    ] = None,
    assignment_type: Annotated[
        str | None,
        Query(description="Optional assignment type: program | acknowledgement"),
    ] = None,
) -> AssignmentAnalyticsResponse:
    return await service.get_assignment_analytics(
        company_id,
        actor=current_user,
        department_id=department_id,
        assignment_type=assignment_type,
    )
