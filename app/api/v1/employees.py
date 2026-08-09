from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.auth_deps import HRUser
from app.api.deps import get_employee_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.employee import EmployeeCreate, EmployeeResponse, EmployeeUpdate
from app.services.employee import EmployeeService

router = APIRouter(prefix="/employees", tags=["Employees"])

ServiceDep = Annotated[EmployeeService, Depends(get_employee_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin or HR role required"},
}


@router.post(
    "",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create employee",
    description=(
        "Create an employee in the caller's company. "
        "`company_id` in the body must match the authenticated tenant."
    ),
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
async def create_employee(
    payload: EmployeeCreate,
    current_user: HRUser,
    service: ServiceDep,
) -> EmployeeResponse:
    employee = await service.create_employee(
        company_id=payload.company_id,
        actor_company_id=current_user.company_id,
        actor_role=current_user.role,
        telegram_user_id=payload.telegram_user_id,
        telegram_chat_id=payload.telegram_chat_id,
        telegram_username=payload.telegram_username,
        full_name=payload.full_name,
        email=payload.email,
        role=payload.role,
        status=payload.status,
        hired_at=payload.hired_at,
    )
    return EmployeeResponse.model_validate(employee)


@router.get(
    "",
    response_model=list[EmployeeResponse],
    summary="List employees",
    description="List employees for the caller's company only.",
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
async def list_employees(
    current_user: HRUser,
    service: ServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter: invited, active, archived"),
    ] = None,
) -> list[EmployeeResponse]:
    employees = await service.list_employees(
        company_id,
        actor_company_id=current_user.company_id,
        offset=offset,
        limit=limit,
        status=status_filter,
    )
    return [EmployeeResponse.model_validate(employee) for employee in employees]


@router.get(
    "/{employee_id}",
    response_model=EmployeeResponse,
    summary="Get employee by ID",
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
async def get_employee(
    employee_id: UUID,
    current_user: HRUser,
    service: ServiceDep,
) -> EmployeeResponse:
    employee = await service.get_employee(
        employee_id,
        company_id=current_user.company_id,
    )
    return EmployeeResponse.model_validate(employee)


@router.patch(
    "/{employee_id}",
    response_model=EmployeeResponse,
    summary="Update employee",
    description="Partially update employee fields within the caller's company.",
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
async def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdate,
    current_user: HRUser,
    service: ServiceDep,
) -> EmployeeResponse:
    employee = await service.update_employee(
        employee_id,
        company_id=current_user.company_id,
        actor_role=current_user.role,
        **payload.model_dump(exclude_unset=True),
    )
    return EmployeeResponse.model_validate(employee)


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete employee",
    description="Delete an employee in the caller's company.",
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
async def delete_employee(
    employee_id: UUID,
    current_user: HRUser,
    service: ServiceDep,
) -> Response:
    await service.delete_employee(
        employee_id,
        company_id=current_user.company_id,
        actor_role=current_user.role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
