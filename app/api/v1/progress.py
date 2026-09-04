from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.auth_deps import EmployeeUser, assert_can_complete_assignment_progress
from app.api.deps import (
    get_assignment_service,
    get_learning_progress_service,
    get_progress_service,
)
from app.api.v1.responses import ERROR_RESPONSES
from app.core.security import verify_bot_service_token
from app.db.models.progress import Progress
from app.schemas.progress import (
    ProgressAdvanceRequest,
    ProgressCompleteRequest,
    ProgressResponse,
)
from app.services.assessment import public_progress_payload
from app.services.assignment import AssignmentService
from app.services.learning_progress import LearningProgressService
from app.services.progress import ProgressService

router = APIRouter(prefix="/progress", tags=["Progress"])

ProgressServiceDep = Annotated[ProgressService, Depends(get_progress_service)]
LearningProgressServiceDep = Annotated[
    LearningProgressService, Depends(get_learning_progress_service)
]
AssignmentServiceDep = Annotated[AssignmentService, Depends(get_assignment_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": "Only the assigned employee may complete their own progress",
    },
}

_MUTATION_RESPONSES = {
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
}


def _progress_response(updated: Progress) -> ProgressResponse:
    return ProgressResponse(
        id=updated.id,
        assignment_id=updated.assignment_id,
        step_id=updated.step_id,
        status=updated.status,
        payload=public_progress_payload(updated.payload or {}),
        started_at=updated.started_at,
        completed_at=updated.completed_at,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        step=None,
    )


async def _assert_owner(
    progress_id: UUID,
    current_user: EmployeeUser,
    progress_service: ProgressService,
    assignment_service: AssignmentService,
):
    progress = await progress_service.get_progress_by_id(
        progress_id,
        company_id=current_user.company_id,
    )
    assignment = await assignment_service.get_assignment(
        progress.assignment_id,
        company_id=current_user.company_id,
    )
    assert_can_complete_assignment_progress(current_user, assignment)
    return progress, assignment


def _telegram_delivery_flags(
    x_telegram_delivery: str | None,
    x_bot_service_token: str | None,
) -> bool:
    telegram_delivery = x_telegram_delivery == "durable"
    if x_telegram_delivery is not None and not telegram_delivery:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Telegram delivery mode",
        )
    if telegram_delivery and not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return telegram_delivery


@router.post(
    "/{progress_id}/start",
    response_model=ProgressResponse,
    summary="Start or resume a progress step",
    description=(
        "Mark a content step in_progress and initialize block_index=0 when "
        "the row is still not_started. Idempotent for an already started step."
    ),
    responses=_MUTATION_RESPONSES,
)
async def start_progress(
    progress_id: UUID,
    current_user: EmployeeUser,
    progress_service: ProgressServiceDep,
    learning_service: LearningProgressServiceDep,
    assignment_service: AssignmentServiceDep,
) -> ProgressResponse:
    await _assert_owner(
        progress_id, current_user, progress_service, assignment_service
    )
    updated = await learning_service.start_or_resume(
        progress_id,
        company_id=current_user.company_id,
    )
    return _progress_response(updated)


@router.post(
    "/{progress_id}/advance",
    response_model=ProgressResponse,
    summary="Advance content block",
    description=(
        "Atomically advance block_index when expected_block_index matches "
        "the stored cursor. Stale or double-click callbacks are no-ops."
    ),
    responses=_MUTATION_RESPONSES,
)
async def advance_progress(
    progress_id: UUID,
    body: ProgressAdvanceRequest,
    current_user: EmployeeUser,
    progress_service: ProgressServiceDep,
    learning_service: LearningProgressServiceDep,
    assignment_service: AssignmentServiceDep,
) -> ProgressResponse:
    await _assert_owner(
        progress_id, current_user, progress_service, assignment_service
    )
    updated = await learning_service.advance_block(
        progress_id,
        company_id=current_user.company_id,
        expected_block_index=body.expected_block_index,
    )
    return _progress_response(updated)


@router.post(
    "/{progress_id}/read",
    response_model=ProgressResponse,
    summary="Complete the final content block",
    description=(
        "Acknowledge the last content block and complete the step through "
        "existing assignment completion rules. Stale expected_block_index is a no-op."
    ),
    responses=_MUTATION_RESPONSES,
)
async def read_progress(
    progress_id: UUID,
    body: ProgressAdvanceRequest,
    current_user: EmployeeUser,
    progress_service: ProgressServiceDep,
    learning_service: LearningProgressServiceDep,
    assignment_service: AssignmentServiceDep,
    x_telegram_delivery: Annotated[
        str | None,
        Header(alias="X-Telegram-Delivery"),
    ] = None,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> ProgressResponse:
    telegram_delivery = _telegram_delivery_flags(
        x_telegram_delivery, x_bot_service_token
    )
    await _assert_owner(
        progress_id, current_user, progress_service, assignment_service
    )
    updated = await learning_service.complete_content_block(
        progress_id,
        company_id=current_user.company_id,
        expected_block_index=body.expected_block_index,
        telegram_outbound_employee_id=(
            current_user.id if telegram_delivery else None
        ),
    )
    return _progress_response(updated)


@router.post(
    "/{progress_id}/complete",
    response_model=ProgressResponse,
    summary="Complete progress step",
    description=(
        "Mark a progress row as completed within the caller's company. "
        "Only the employee assigned to the parent assignment may complete steps."
    ),
    responses=_MUTATION_RESPONSES,
)
async def complete_progress(
    progress_id: UUID,
    current_user: EmployeeUser,
    progress_service: ProgressServiceDep,
    assignment_service: AssignmentServiceDep,
    payload: ProgressCompleteRequest | None = None,
    x_telegram_delivery: Annotated[
        str | None,
        Header(alias="X-Telegram-Delivery"),
    ] = None,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> ProgressResponse:
    telegram_delivery = _telegram_delivery_flags(
        x_telegram_delivery, x_bot_service_token
    )
    await _assert_owner(
        progress_id, current_user, progress_service, assignment_service
    )

    body = payload or ProgressCompleteRequest()
    updated = await progress_service.complete_by_progress_id(
        progress_id,
        company_id=current_user.company_id,
        payload=body.payload,
        telegram_outbound_employee_id=(
            current_user.id if telegram_delivery else None
        ),
    )
    return _progress_response(updated)
