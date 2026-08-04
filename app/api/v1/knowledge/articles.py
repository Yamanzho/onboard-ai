from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import EmployeeUser, HRUser
from app.api.deps import get_article_service
from app.api.v1.responses import ERROR_RESPONSES
from app.schemas.knowledge.article import (
    ArticleCreate,
    ArticleListResponse,
    ArticleResponse,
    ArticleUpdate,
)
from app.services.knowledge.article_service import ArticleService

router = APIRouter(prefix="/knowledge/articles", tags=["Knowledge"])

ArticleServiceDep = Annotated[ArticleService, Depends(get_article_service)]

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
    response_model=ArticleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create knowledge article",
    description=(
        "Create a draft article with version 1, optional category, and tags. "
        "Content is stored on an immutable version row."
    ),
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
async def create_article(
    payload: ArticleCreate,
    current_user: HRUser,
    service: ArticleServiceDep,
) -> ArticleResponse:
    article = await service.create_article(
        company_id=payload.company_id,
        actor_company_id=current_user.company_id,
        title=payload.title,
        body=payload.body,
        body_format=payload.body_format,
        category_id=payload.category_id,
        visibility=payload.visibility,
        tag_ids=payload.tag_ids,
        change_summary=payload.change_summary,
        created_by_id=current_user.id,
    )
    return ArticleResponse.model_validate(article)


@router.get(
    "",
    response_model=ArticleListResponse,
    summary="List knowledge articles",
    description="List articles for the caller's company with optional filters.",
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
async def list_articles(
    current_user: HRUser,
    service: ArticleServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter by draft|published|archived"),
    ] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    tag_id: Annotated[UUID | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> ArticleListResponse:
    articles = await service.list_articles(
        company_id,
        actor_company_id=current_user.company_id,
        status=status_filter,
        category_id=category_id,
        tag_id=tag_id,
        offset=offset,
        limit=limit,
    )
    return ArticleListResponse(
        items=[ArticleResponse.model_validate(article) for article in articles],
    )


@router.get(
    "/{article_id}",
    response_model=ArticleResponse,
    summary="Get knowledge article",
    description="Get an article with current version and tags within the caller's company.",
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
async def get_article(
    article_id: UUID,
    current_user: EmployeeUser,
    service: ArticleServiceDep,
) -> ArticleResponse:
    article = await service.get_article(
        article_id,
        company_id=current_user.company_id,
    )
    return ArticleResponse.model_validate(article)


@router.put(
    "/{article_id}",
    response_model=ArticleResponse,
    summary="Update knowledge article",
    description=(
        "Update metadata and/or content. Content changes create a new immutable "
        "version and advance current_version_id; previous versions are never mutated."
    ),
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
async def update_article(
    article_id: UUID,
    payload: ArticleUpdate,
    current_user: HRUser,
    service: ArticleServiceDep,
) -> ArticleResponse:
    article = await service.update_article(
        article_id,
        company_id=current_user.company_id,
        created_by_id=current_user.id,
        **payload.model_dump(exclude_unset=True),
    )
    return ArticleResponse.model_validate(article)


@router.post(
    "/{article_id}/publish",
    response_model=ArticleResponse,
    summary="Publish knowledge article",
    description="Transition a draft article to published.",
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
async def publish_article(
    article_id: UUID,
    current_user: HRUser,
    service: ArticleServiceDep,
) -> ArticleResponse:
    article = await service.publish_article(
        article_id,
        company_id=current_user.company_id,
    )
    return ArticleResponse.model_validate(article)


@router.post(
    "/{article_id}/archive",
    response_model=ArticleResponse,
    summary="Archive knowledge article",
    description="Archive a draft or published article.",
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
async def archive_article(
    article_id: UUID,
    current_user: HRUser,
    service: ArticleServiceDep,
) -> ArticleResponse:
    article = await service.archive_article(
        article_id,
        company_id=current_user.company_id,
    )
    return ArticleResponse.model_validate(article)
