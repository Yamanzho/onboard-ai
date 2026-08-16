from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import HRUser
from app.api.deps import get_company_audit_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.analytics import CompanyAuditLogListResponse, CompanyAuditLogResponse
from app.services.company_audit import CompanyAuditService

router = APIRouter(prefix="/audit-logs", tags=["Audit"])

CompanyAuditServiceDep = Annotated[
    CompanyAuditService, Depends(get_company_audit_service)
]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin or HR role required"},
}


@router.get(
    "",
    response_model=CompanyAuditLogListResponse,
    summary="List company audit events",
    description=(
        "HR/Admin only. Returns tenant-scoped audit events for the caller's company. "
        "Credentials and invite tokens are never stored."
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
async def list_company_audit_logs(
    current_user: HRUser,
    service: CompanyAuditServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    action: Annotated[str | None, Query()] = None,
    resource_type: Annotated[str | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> CompanyAuditLogListResponse:
    events = await service.list_events(
        company_id,
        actor_company_id=current_user.company_id,
        action=action,
        resource_type=resource_type,
        offset=offset,
        limit=limit,
    )
    return CompanyAuditLogListResponse(
        items=[CompanyAuditLogResponse.model_validate(row) for row in events],
    )
