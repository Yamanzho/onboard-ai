from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import EmployeeUser, KnowledgeManageUser
from app.api.deps import get_category_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.knowledge.category import CategoryCreate, CategoryResponse, CategoryUpdate
from app.services.knowledge.category_service import CategoryService

router = APIRouter(prefix="/knowledge/categories", tags=["Knowledge"])

CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]

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
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create knowledge category",
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
async def create_category(
    payload: CategoryCreate,
    current_user: KnowledgeManageUser,
    service: CategoryServiceDep,
) -> CategoryResponse:
    category = await service.create_category(
        company_id=payload.company_id,
        actor_company_id=current_user.company_id,
        name=payload.name,
        slug=payload.slug,
        parent_id=payload.parent_id,
        position=payload.position,
    )
    return CategoryResponse.model_validate(category)


@router.get(
    "",
    response_model=list[CategoryResponse],
    summary="List knowledge categories",
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
async def list_categories(
    current_user: KnowledgeManageUser,
    service: CategoryServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    parent_id: Annotated[UUID | None, Query()] = None,
    roots_only: Annotated[bool, Query()] = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CategoryResponse]:
    categories = await service.list_categories(
        company_id,
        actor_company_id=current_user.company_id,
        parent_id=parent_id,
        roots_only=roots_only,
        offset=offset,
        limit=limit,
    )
    return [CategoryResponse.model_validate(category) for category in categories]


@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Get knowledge category",
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
async def get_category(
    category_id: UUID,
    current_user: EmployeeUser,
    service: CategoryServiceDep,
) -> CategoryResponse:
    category = await service.get_category(
        category_id,
        company_id=current_user.company_id,
    )
    return CategoryResponse.model_validate(category)


@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Update knowledge category",
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
async def update_category(
    category_id: UUID,
    payload: CategoryUpdate,
    current_user: KnowledgeManageUser,
    service: CategoryServiceDep,
) -> CategoryResponse:
    category = await service.update_category(
        category_id,
        company_id=current_user.company_id,
        **payload.model_dump(exclude_unset=True),
    )
    return CategoryResponse.model_validate(category)
