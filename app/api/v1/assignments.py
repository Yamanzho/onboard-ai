from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.auth_deps import (
    EmployeeUser,
    HRUser,
    assert_can_list_employee_assignments,
    assert_can_view_assignment_progress,
)
from app.api.deps import get_assignment_service, get_progress_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.assignment import AssignmentCreate, AssignmentResponse
from app.schemas.progress import AssignmentProgressResponse, ProgressResponse
from app.services.assignment import AssignmentService
from app.services.progress import ProgressService

router = APIRouter(tags=["Assignments"])

AssignmentServiceDep = Annotated[AssignmentService, Depends(get_assignment_service)]
ProgressServiceDep = Annotated[ProgressService, Depends(get_progress_service)]

_HR_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin or HR role required"},
}

_PROGRESS_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": "Employees may view only their own progress; HR/admin may view any within tenant",
    },
}

_ASSIGNMENT_LIST_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": "Employees may list only their own assignments; HR/admin may list any within tenant",
    },
}


@router.post(
    "/assignments",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign program to employee",
    description="Create an assignment within the caller's company.",
    responses={
        **_HR_AUTH_RESPONSES,
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
async def create_assignment(
    payload: AssignmentCreate,
    current_user: HRUser,
    service: AssignmentServiceDep,
) -> AssignmentResponse:
    assignment = await service.assign_employee(
        employee_id=payload.employee_id,
        program_id=payload.program_id,
        company_id=current_user.company_id,
        assigned_by_id=payload.assigned_by_id,
        due_at=payload.due_at,
    )
    return AssignmentResponse.model_validate(assignment)


@router.get(
    "/employees/{employee_id}/assignments",
    response_model=list[AssignmentResponse],
    summary="List employee assignments",
    description=(
        "List assignments for an employee within the caller's company. "
        "Employees may list only their own assignments; HR/admin may list any."
    ),
    tags=["Assignments"],
    responses={
        **_ASSIGNMENT_LIST_AUTH_RESPONSES,
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
async def list_employee_assignments(
    employee_id: UUID,
    current_user: EmployeeUser,
    service: AssignmentServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description="Optional status filter: pending, in_progress, completed, cancelled",
        ),
    ] = None,
) -> list[AssignmentResponse]:
    assert_can_list_employee_assignments(current_user, employee_id)
    assignments = await service.get_employee_assignments(
        employee_id,
        company_id=current_user.company_id,
        offset=offset,
        limit=limit,
        status=status_filter,
    )
    return [AssignmentResponse.model_validate(item) for item in assignments]


@router.delete(
    "/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel assignment",
    description="Cancel an active assignment in the caller's company.",
    responses={
        **_HR_AUTH_RESPONSES,
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
async def cancel_assignment(
    assignment_id: UUID,
    current_user: HRUser,
    service: AssignmentServiceDep,
) -> Response:
    await service.cancel_assignment(
        assignment_id,
        company_id=current_user.company_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/assignments/{assignment_id}/progress",
    response_model=AssignmentProgressResponse,
    summary="Get assignment progress",
    tags=["Progress"],
    responses={
        **_PROGRESS_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def get_assignment_progress(
    assignment_id: UUID,
    current_user: EmployeeUser,
    assignments: AssignmentServiceDep,
    service: ProgressServiceDep,
) -> AssignmentProgressResponse:
    assignment = await assignments.get_assignment(
        assignment_id,
        company_id=current_user.company_id,
    )
    assert_can_view_assignment_progress(current_user, assignment)

    items = await service.get_progress(
        assignment_id,
        company_id=current_user.company_id,
    )
    percentage = await service.calculate_progress_percentage(
        assignment_id,
        company_id=current_user.company_id,
    )
    return AssignmentProgressResponse(
        percentage=percentage,
        items=[ProgressResponse.model_validate(item) for item in items],
    )
