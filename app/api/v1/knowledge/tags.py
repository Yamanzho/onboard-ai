from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import EmployeeUser, KnowledgeManageUser
from app.api.deps import get_tag_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.knowledge.tag import TagCreate, TagResponse, TagUpdate
from app.services.knowledge.tag_service import TagService

router = APIRouter(prefix="/knowledge/tags", tags=["Knowledge"])

TagServiceDep = Annotated[TagService, Depends(get_tag_service)]

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
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create knowledge tag",
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
async def create_tag(
    payload: TagCreate,
    current_user: KnowledgeManageUser,
    service: TagServiceDep,
) -> TagResponse:
    tag = await service.create_tag(
        company_id=payload.company_id,
        actor_company_id=current_user.company_id,
        name=payload.name,
        slug=payload.slug,
    )
    return TagResponse.model_validate(tag)


@router.get(
    "",
    response_model=list[TagResponse],
    summary="List knowledge tags",
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
async def list_tags(
    current_user: KnowledgeManageUser,
    service: TagServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    prefix: Annotated[
        str | None,
        Query(description="Optional slug prefix filter"),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[TagResponse]:
    tags = await service.list_tags(
        company_id,
        actor_company_id=current_user.company_id,
        offset=offset,
        limit=limit,
        prefix=prefix,
    )
    return [TagResponse.model_validate(tag) for tag in tags]


@router.get(
    "/{tag_id}",
    response_model=TagResponse,
    summary="Get knowledge tag",
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
async def get_tag(
    tag_id: UUID,
    current_user: EmployeeUser,
    service: TagServiceDep,
) -> TagResponse:
    tag = await service.get_tag(
        tag_id,
        company_id=current_user.company_id,
    )
    return TagResponse.model_validate(tag)


@router.patch(
    "/{tag_id}",
    response_model=TagResponse,
    summary="Update knowledge tag",
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
async def update_tag(
    tag_id: UUID,
    payload: TagUpdate,
    current_user: KnowledgeManageUser,
    service: TagServiceDep,
) -> TagResponse:
    tag = await service.update_tag(
        tag_id,
        company_id=current_user.company_id,
        **payload.model_dump(exclude_unset=True),
    )
    return TagResponse.model_validate(tag)
