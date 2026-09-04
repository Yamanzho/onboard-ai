from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import HRUser
from app.api.deps import get_department_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.department import DepartmentCreate, DepartmentResponse, DepartmentUpdate
from app.services.department import DepartmentService

router = APIRouter(prefix="/departments", tags=["Departments"])

DepartmentServiceDep = Annotated[DepartmentService, Depends(get_department_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin or HR role required"},
}


@router.post(
    "",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create department",
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
async def create_department(
    payload: DepartmentCreate,
    current_user: HRUser,
    service: DepartmentServiceDep,
) -> DepartmentResponse:
    department = await service.create_department(
        company_id=payload.company_id,
        actor_company_id=current_user.company_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        is_active=payload.is_active,
        actor_employee_id=current_user.id,
    )
    return DepartmentResponse.model_validate(department)


@router.get(
    "",
    response_model=list[DepartmentResponse],
    summary="List departments",
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
async def list_departments(
    current_user: HRUser,
    service: DepartmentServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    is_active: Annotated[bool | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[DepartmentResponse]:
    departments = await service.list_departments(
        company_id,
        actor_company_id=current_user.company_id,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return [DepartmentResponse.model_validate(item) for item in departments]


@router.get(
    "/{department_id}",
    response_model=DepartmentResponse,
    summary="Get department",
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
async def get_department(
    department_id: UUID,
    current_user: HRUser,
    service: DepartmentServiceDep,
) -> DepartmentResponse:
    department = await service.get_department(
        department_id,
        company_id=current_user.company_id,
    )
    return DepartmentResponse.model_validate(department)


@router.patch(
    "/{department_id}",
    response_model=DepartmentResponse,
    summary="Update department",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: ERROR_RESPONSES[status.HTTP_400_BAD_REQUEST],
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
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    current_user: HRUser,
    service: DepartmentServiceDep,
) -> DepartmentResponse:
    department = await service.update_department(
        department_id,
        company_id=current_user.company_id,
        actor_employee_id=current_user.id,
        **payload.model_dump(exclude_unset=True),
    )
    return DepartmentResponse.model_validate(department)
