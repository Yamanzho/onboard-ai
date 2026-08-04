from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.auth_deps import AdminUser
from app.api.deps import get_company_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.company import CompanyCreate, CompanyResponse, CompanyUpdate
from app.services.company import CompanyService

router = APIRouter(prefix="/companies", tags=["Companies"])

ServiceDep = Annotated[CompanyService, Depends(get_company_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin role required"},
}


@router.get(
    "",
    response_model=list[CompanyResponse],
    summary="List companies",
    description="Return the caller's own company only (tenant-scoped).",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def list_companies(
    current_user: AdminUser,
    service: ServiceDep,
    offset: Annotated[int, Query(ge=0, description="Number of items to skip")] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=1000, description="Maximum number of items to return"),
    ] = 100,
) -> list[CompanyResponse]:
    companies = await service.list_companies(
        actor_company_id=current_user.company_id,
        offset=offset,
        limit=limit,
    )
    return [CompanyResponse.model_validate(company) for company in companies]


@router.get(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Get company by ID",
    description="Return a company by UUID. Cross-tenant IDs return 404.",
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
async def get_company(
    company_id: UUID,
    current_user: AdminUser,
    service: ServiceDep,
) -> CompanyResponse:
    company = await service.get_company(
        company_id,
        actor_company_id=current_user.company_id,
    )
    return CompanyResponse.model_validate(company)


@router.post(
    "",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create company",
    description=(
        "Create a new company tenant. Slug must be unique. "
        "Note: this is a platform bootstrap operation (creates a new tenant)."
    ),
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_409_CONFLICT: ERROR_RESPONSES[status.HTTP_409_CONFLICT],
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def create_company(
    payload: CompanyCreate,
    _: AdminUser,
    service: ServiceDep,
) -> CompanyResponse:
    company = await service.create_company(
        name=payload.name,
        slug=payload.slug,
        timezone=payload.timezone,
        settings=payload.settings,
    )
    return CompanyResponse.model_validate(company)


@router.patch(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Update company",
    description="Partially update the caller's own company. Cross-tenant IDs return 404.",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_409_CONFLICT: ERROR_RESPONSES[status.HTTP_409_CONFLICT],
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    current_user: AdminUser,
    service: ServiceDep,
) -> CompanyResponse:
    values = payload.model_dump(exclude_unset=True)
    company = await service.update_company(
        company_id,
        actor_company_id=current_user.company_id,
        **values,
    )
    return CompanyResponse.model_validate(company)


@router.delete(
    "/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete company",
    description="Delete the caller's own company. Cross-tenant IDs return 404.",
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
async def delete_company(
    company_id: UUID,
    current_user: AdminUser,
    service: ServiceDep,
) -> Response:
    await service.delete_company(
        company_id,
        actor_company_id=current_user.company_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
