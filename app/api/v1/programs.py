from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import EmployeeUser, HRUser
from app.api.deps import get_onboarding_program_service, get_step_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.onboarding_program import ProgramCreate, ProgramResponse, ProgramUpdate
from app.schemas.step import StepCreate, StepReorderRequest, StepResponse
from app.services.onboarding_program import OnboardingProgramService
from app.services.step import StepService

router = APIRouter(prefix="/programs", tags=["Programs"])

ProgramServiceDep = Annotated[OnboardingProgramService, Depends(get_onboarding_program_service)]
StepServiceDep = Annotated[StepService, Depends(get_step_service)]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin or HR role required"},
}

_READ_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": "Authenticated employee required (tenant-scoped read)",
    },
}


@router.post(
    "",
    response_model=ProgramResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create onboarding program",
    description="Create a draft program for the caller's company.",
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
async def create_program(
    payload: ProgramCreate,
    current_user: HRUser,
    service: ProgramServiceDep,
) -> ProgramResponse:
    program = await service.create_program(
        company_id=payload.company_id,
        actor_company_id=current_user.company_id,
        title=payload.title,
        description=payload.description,
    )
    return ProgramResponse.model_validate(program)


@router.get(
    "",
    response_model=list[ProgramResponse],
    summary="List onboarding programs",
    description="List programs for the caller's company only.",
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
async def list_programs(
    current_user: HRUser,
    service: ProgramServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    is_active: Annotated[
        bool | None,
        Query(description="Filter by published (true) or draft/archived (false)"),
    ] = None,
) -> list[ProgramResponse]:
    programs = await service.list_programs(
        company_id,
        actor_company_id=current_user.company_id,
        offset=offset,
        limit=limit,
        is_active=is_active,
    )
    return [ProgramResponse.model_validate(program) for program in programs]


@router.get(
    "/{program_id}",
    response_model=ProgramResponse,
    summary="Get onboarding program",
    description=(
        "Get a program within the caller's company. "
        "Any authenticated employee in the tenant may read program metadata "
        "(needed for Telegram onboarding UX)."
    ),
    responses={
        **_READ_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def get_program(
    program_id: UUID,
    current_user: EmployeeUser,
    service: ProgramServiceDep,
) -> ProgramResponse:
    program = await service.get_program(
        program_id,
        company_id=current_user.company_id,
    )
    return ProgramResponse.model_validate(program)


@router.patch(
    "/{program_id}",
    response_model=ProgramResponse,
    summary="Update onboarding program",
    description="Update title/description within the caller's company.",
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
async def update_program(
    program_id: UUID,
    payload: ProgramUpdate,
    current_user: HRUser,
    service: ProgramServiceDep,
) -> ProgramResponse:
    program = await service.update_program(
        program_id,
        company_id=current_user.company_id,
        **payload.model_dump(exclude_unset=True),
    )
    return ProgramResponse.model_validate(program)


@router.post(
    "/{program_id}/publish",
    response_model=ProgramResponse,
    summary="Publish onboarding program",
    description="Mark program as active. Requires at least one step.",
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
async def publish_program(
    program_id: UUID,
    current_user: HRUser,
    service: ProgramServiceDep,
) -> ProgramResponse:
    program = await service.publish_program(
        program_id,
        company_id=current_user.company_id,
    )
    return ProgramResponse.model_validate(program)


@router.post(
    "/{program_id}/archive",
    response_model=ProgramResponse,
    summary="Archive onboarding program",
    description="Deactivate a program so it can no longer be newly assigned.",
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
async def archive_program(
    program_id: UUID,
    current_user: HRUser,
    service: ProgramServiceDep,
) -> ProgramResponse:
    program = await service.archive_program(
        program_id,
        company_id=current_user.company_id,
    )
    return ProgramResponse.model_validate(program)


@router.post(
    "/{program_id}/steps",
    response_model=StepResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create program step",
    tags=["Steps"],
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
async def create_step(
    program_id: UUID,
    payload: StepCreate,
    current_user: HRUser,
    service: StepServiceDep,
) -> StepResponse:
    step = await service.create_step(
        program_id=program_id,
        company_id=current_user.company_id,
        title=payload.title,
        description=payload.description,
        step_type=payload.step_type,
        position=payload.position,
        content=payload.content,
        is_required=payload.is_required,
        estimated_minutes=payload.estimated_minutes,
    )
    return StepResponse.model_validate(step)


@router.post(
    "/{program_id}/steps/reorder",
    response_model=list[StepResponse],
    summary="Reorder program steps",
    description="Provide the full ordered list of step IDs for the program.",
    tags=["Steps"],
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
async def reorder_steps(
    program_id: UUID,
    payload: StepReorderRequest,
    current_user: HRUser,
    service: StepServiceDep,
) -> list[StepResponse]:
    steps = await service.reorder_steps(
        program_id,
        payload.step_ids,
        company_id=current_user.company_id,
    )
    return [StepResponse.model_validate(step) for step in steps]
