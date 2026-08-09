from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.auth_deps import EmployeeUser, assert_can_complete_assignment_progress
from app.api.deps import get_assignment_service, get_progress_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.progress import ProgressCompleteRequest, ProgressResponse
from app.services.assignment import AssignmentService
from app.services.progress import ProgressService

router = APIRouter(prefix="/progress", tags=["Progress"])

ProgressServiceDep = Annotated[ProgressService, Depends(get_progress_service)]
AssignmentServiceDep = Annotated[AssignmentService, Depends(get_assignment_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": "Only the assigned employee may complete their own progress",
    },
}


@router.post(
    "/{progress_id}/complete",
    response_model=ProgressResponse,
    summary="Complete progress step",
    description=(
        "Mark a progress row as completed within the caller's company. "
        "Only the employee assigned to the parent assignment may complete steps."
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
async def complete_progress(
    progress_id: UUID,
    current_user: EmployeeUser,
    progress_service: ProgressServiceDep,
    assignment_service: AssignmentServiceDep,
    payload: ProgressCompleteRequest | None = None,
) -> ProgressResponse:
    progress = await progress_service.get_progress_by_id(
        progress_id,
        company_id=current_user.company_id,
    )
    assignment = await assignment_service.get_assignment(
        progress.assignment_id,
        company_id=current_user.company_id,
    )
    assert_can_complete_assignment_progress(current_user, assignment)

    body = payload or ProgressCompleteRequest()
    updated = await progress_service.complete_by_progress_id(
        progress_id,
        company_id=current_user.company_id,
        payload=body.payload,
    )
    # Explicit construction — ORM Progress.step relationship is not loaded here.
    return ProgressResponse(
        id=updated.id,
        assignment_id=updated.assignment_id,
        step_id=updated.step_id,
        status=updated.status,
        payload=updated.payload or {},
        started_at=updated.started_at,
        completed_at=updated.completed_at,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        step=None,
    )
