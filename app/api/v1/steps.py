from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.auth_deps import HRUser
from app.api.deps import get_step_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.step import StepResponse, StepUpdate
from app.services.step import StepService

router = APIRouter(prefix="/steps", tags=["Steps"])

StepServiceDep = Annotated[StepService, Depends(get_step_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin or HR role required"},
}


@router.patch(
    "/{step_id}",
    response_model=StepResponse,
    summary="Update step",
    description="Partially update a step in the caller's company.",
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
async def update_step(
    step_id: UUID,
    payload: StepUpdate,
    current_user: HRUser,
    service: StepServiceDep,
) -> StepResponse:
    step = await service.update_step(
        step_id,
        company_id=current_user.company_id,
        **payload.model_dump(exclude_unset=True),
    )
    return StepResponse.model_validate(step)


@router.delete(
    "/{step_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete step",
    description="Delete a step in the caller's company. Fails if progress rows exist.",
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
async def delete_step(
    step_id: UUID,
    current_user: HRUser,
    service: StepServiceDep,
) -> Response:
    await service.delete_step(
        step_id,
        company_id=current_user.company_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
