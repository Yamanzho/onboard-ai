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
from app.db.enums import EmployeeRole
from app.schemas.assignment import (
    AssignmentBulkCreateResponse,
    AssignmentCreate,
    AssignmentResponse,
)
from app.schemas.progress import (
    AssignmentProgressResponse,
    ProgressResponse,
    ProgressStepInfo,
)
from app.services.assessment import public_progress_payload
from app.services.assignment import AssignmentService
from app.services.course_snapshot import resolve_progress_step_fields
from app.services.progress import ProgressService
from app.services.step_content import public_step_content

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
        "description": (
            "Employees may view only their own progress; "
            "HR/admin may view any within tenant"
        ),
    },
}

_ASSIGNMENT_LIST_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": (
            "Employees may list only their own assignments; "
            "HR/admin may list any within tenant"
        ),
    },
}


@router.post(
    "/assignments",
    response_model=AssignmentResponse | AssignmentBulkCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign program to employee(s)",
    description=(
        "Create assignment(s) within the caller's company. "
        "A body with only employee_id returns a single assignment. "
        "employee_ids and/or department_ids return a bulk result. "
        "Department targeting snapshots current members; future members are not assigned."
    ),
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
) -> AssignmentResponse | AssignmentBulkCreateResponse:
    if payload.is_legacy_single:
        assert payload.employee_id is not None
        assignment = await service.assign_employee(
            employee_id=payload.employee_id,
            program_id=payload.program_id,
            company_id=current_user.company_id,
            assigned_by_id=payload.assigned_by_id,
            due_at=payload.due_at,
            priority=payload.priority,
            actor_employee_id=current_user.id,
        )
        return AssignmentResponse.model_validate(assignment)

    employee_ids = list(payload.employee_ids)
    if payload.employee_id is not None:
        employee_ids.append(payload.employee_id)
    created = await service.create_many(
        company_id=current_user.company_id,
        program_id=payload.program_id,
        employee_ids=employee_ids,
        department_ids=payload.department_ids,
        assigned_by_id=payload.assigned_by_id,
        due_at=payload.due_at,
        priority=payload.priority,
        deadline_overrides=payload.deadline_overrides,
        actor_employee_id=current_user.id,
        stamp_batch=True,
    )
    items = [AssignmentResponse.model_validate(item) for item in created]
    return AssignmentBulkCreateResponse(
        items=items,
        source_batch_id=created[0].source_batch_id if created else None,
        count=len(items),
    )


@router.get(
    "/assignments",
    response_model=list[AssignmentResponse],
    summary="List company assignments",
    description="List assignments for the caller's company only.",
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
async def list_assignments(
    current_user: HRUser,
    service: AssignmentServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description="Optional status filter: pending, in_progress, completed, cancelled",
        ),
    ] = None,
    employee_id: Annotated[
        UUID | None,
        Query(description="Optional filter by employee"),
    ] = None,
) -> list[AssignmentResponse]:
    assignments = await service.list_assignments(
        company_id,
        actor_company_id=current_user.company_id,
        offset=offset,
        limit=limit,
        status=status_filter,
        employee_id=employee_id,
    )
    return [AssignmentResponse.model_validate(item) for item in assignments]


@router.get(
    "/assignments/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Get assignment by ID",
    description="Get an assignment within the caller's company.",
    responses={
        **_HR_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def get_assignment(
    assignment_id: UUID,
    current_user: HRUser,
    service: AssignmentServiceDep,
) -> AssignmentResponse:
    assignment = await service.get_assignment(
        assignment_id,
        company_id=current_user.company_id,
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
        actor_employee_id=current_user.id,
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
    step_by_id = await service.get_steps_for_progress_items(
        items,
        company_id=current_user.company_id,
    )
    responses: list[ProgressResponse] = []
    snapshot = assignment.structure_snapshot
    for item in items:
        live_step = step_by_id.get(item.step_id)
        fields = resolve_progress_step_fields(
            item.step_id,
            live_step=live_step,
            snapshot=snapshot,
        )
        content = fields["content"] if fields is not None else {}
        item_payload = item.payload or {}
        if current_user.role == EmployeeRole.EMPLOYEE.value:
            content = public_step_content(content)
            item_payload = public_progress_payload(item_payload)
        step_info = (
            ProgressStepInfo(
                title=fields["title"],
                description=fields["description"],
                step_type=fields["step_type"],
                content=content,
                position=fields["position"],
            )
            if fields is not None
            else None
        )
        # Build explicitly — Progress ORM also has a ``step`` relationship that
        # would DetachedInstanceError under model_validate(from_attributes).
        responses.append(
            ProgressResponse(
                id=item.id,
                assignment_id=item.assignment_id,
                step_id=item.step_id,
                status=item.status,
                payload=item_payload,
                started_at=item.started_at,
                completed_at=item.completed_at,
                created_at=item.created_at,
                updated_at=item.updated_at,
                step=step_info,
            )
        )
    return AssignmentProgressResponse(
        percentage=percentage,
        items=responses,
    )
