from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import ResponsibilitiesManageUser, ResponsibilitiesViewUser
from app.api.deps import get_question_topic_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.question_topic import (
    QuestionTopicCreate,
    QuestionTopicResponse,
    QuestionTopicUpdate,
    TopicResponsibilityPayload,
)
from app.services.question_topic import QuestionTopicService

router = APIRouter(prefix="/topics", tags=["Topics"])

QuestionTopicServiceDep = Annotated[
    QuestionTopicService,
    Depends(get_question_topic_service),
]

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {"description": "Admin or HR role required"},
}


@router.post(
    "",
    response_model=QuestionTopicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create question topic",
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
async def create_topic(
    payload: QuestionTopicCreate,
    current_user: ResponsibilitiesManageUser,
    service: QuestionTopicServiceDep,
) -> QuestionTopicResponse:
    topic = await service.create_topic(
        company_id=payload.company_id,
        actor_company_id=current_user.company_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        is_active=payload.is_active,
        department_id=payload.department_id,
        employee_id=payload.employee_id,
        actor_employee_id=current_user.id,
    )
    return QuestionTopicResponse.model_validate(topic)


@router.get(
    "",
    response_model=list[QuestionTopicResponse],
    summary="List question topics",
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
async def list_topics(
    current_user: ResponsibilitiesViewUser,
    service: QuestionTopicServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    is_active: Annotated[bool | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[QuestionTopicResponse]:
    topics = await service.list_topics(
        company_id,
        actor_company_id=current_user.company_id,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return [QuestionTopicResponse.model_validate(item) for item in topics]


@router.get(
    "/{topic_id}",
    response_model=QuestionTopicResponse,
    summary="Get question topic",
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
async def get_topic(
    topic_id: UUID,
    current_user: ResponsibilitiesViewUser,
    service: QuestionTopicServiceDep,
) -> QuestionTopicResponse:
    topic = await service.get_topic(topic_id, company_id=current_user.company_id)
    return QuestionTopicResponse.model_validate(topic)


@router.patch(
    "/{topic_id}",
    response_model=QuestionTopicResponse,
    summary="Update question topic",
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
async def update_topic(
    topic_id: UUID,
    payload: QuestionTopicUpdate,
    current_user: ResponsibilitiesManageUser,
    service: QuestionTopicServiceDep,
) -> QuestionTopicResponse:
    topic = await service.update_topic(
        topic_id,
        company_id=current_user.company_id,
        actor_employee_id=current_user.id,
        **payload.model_dump(exclude_unset=True),
    )
    return QuestionTopicResponse.model_validate(topic)


@router.put(
    "/{topic_id}/responsibility",
    response_model=QuestionTopicResponse,
    summary="Set topic responsibility",
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
async def set_topic_responsibility(
    topic_id: UUID,
    payload: TopicResponsibilityPayload,
    current_user: ResponsibilitiesManageUser,
    service: QuestionTopicServiceDep,
) -> QuestionTopicResponse:
    topic = await service.set_responsibility(
        topic_id,
        company_id=current_user.company_id,
        department_id=payload.department_id,
        employee_id=payload.employee_id,
        actor_employee_id=current_user.id,
    )
    return QuestionTopicResponse.model_validate(topic)
