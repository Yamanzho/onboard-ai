from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.auth_deps import EmployeeUser, HRUser
from app.api.deps import get_article_service, get_chunk_indexer
from app.api.v1.responses import ERROR_RESPONSES
from app.core.exceptions import ValidationError
from app.schemas.knowledge.article import (
    ArticleCreate,
    ArticleListResponse,
    ArticleResponse,
    ArticleUpdate,
    CorpusReindexResponse,
    article_response,
)
from app.schemas.knowledge.version import (
    ArticleVersionListResponse,
    ArticleVersionResponse,
    ArticleVersionSummary,
)
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.knowledge.article_service import ArticleService

router = APIRouter(prefix="/knowledge/articles", tags=["Knowledge"])

ArticleServiceDep = Annotated[ArticleService, Depends(get_article_service)]
ChunkIndexerDep = Annotated[KnowledgeChunkIndexer, Depends(get_chunk_indexer)]

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
        program_ids=payload.program_ids,
    )
    return article_response(article)


@router.get(
    "",
    response_model=ArticleListResponse,
    summary="List knowledge articles",
    description=(
        "List articles for the caller's company. HR/Admin see all statuses. "
        "Employees only see published articles allowed by visibility."
    ),
    responses={
        **_READ_AUTH_RESPONSES,
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
    current_user: EmployeeUser,
    service: ArticleServiceDep,
    company_id: Annotated[UUID, Query(description="Company tenant ID")],
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter by draft|published|archived"),
    ] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    tag_id: Annotated[UUID | None, Query()] = None,
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Search title, body, category, and tags of the current version",
        ),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> ArticleListResponse:
    articles = await service.list_articles(
        company_id,
        actor_company_id=current_user.company_id,
        status=status_filter,
        category_id=category_id,
        tag_id=tag_id,
        q=q,
        offset=offset,
        limit=limit,
        actor_role=current_user.role,
        actor_employee_id=current_user.id,
    )
    return ArticleListResponse(
        items=[article_response(article) for article in articles],
    )


@router.get(
    "/{article_id}",
    response_model=ArticleResponse,
    summary="Get knowledge article",
    description=(
        "Get an article with current version and tags within the caller's company. "
        "HR/Admin may read any status. Employees may only read **published** articles "
        "allowed by visibility (`company`, or `program` via article links + assignment)."
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
async def get_article(
    article_id: UUID,
    current_user: EmployeeUser,
    service: ArticleServiceDep,
) -> ArticleResponse:
    article = await service.get_article(
        article_id,
        company_id=current_user.company_id,
        actor_role=current_user.role,
        actor_employee_id=current_user.id,
    )
    return article_response(article)


@router.get(
    "/{article_id}/versions",
    response_model=ArticleVersionListResponse,
    summary="List article versions",
    description="HR/Admin only. Lists immutable versions newest first (no full body).",
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
async def list_article_versions(
    article_id: UUID,
    current_user: HRUser,
    service: ArticleServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> ArticleVersionListResponse:
    versions = await service.list_versions(
        article_id,
        company_id=current_user.company_id,
        actor_role=current_user.role,
        offset=offset,
        limit=limit,
    )
    return ArticleVersionListResponse(
        items=[ArticleVersionSummary.model_validate(row) for row in versions],
    )


@router.get(
    "/{article_id}/versions/{version}",
    response_model=ArticleVersionResponse,
    summary="Get a historical article version",
    description="HR/Admin only. Returns full title/body for one immutable version.",
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
async def get_article_version(
    article_id: UUID,
    version: int,
    current_user: HRUser,
    service: ArticleServiceDep,
) -> ArticleVersionResponse:
    row = await service.get_version(
        article_id,
        version,
        company_id=current_user.company_id,
        actor_role=current_user.role,
    )
    return ArticleVersionResponse.model_validate(row)


@router.post(
    "/{article_id}/versions/{version}/restore",
    response_model=ArticleResponse,
    summary="Restore an article version",
    description=(
        "Creates a new immutable version copying title/body from the selected "
        "historical version. Does not mutate past rows."
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
async def restore_article_version(
    article_id: UUID,
    version: int,
    current_user: HRUser,
    service: ArticleServiceDep,
) -> ArticleResponse:
    article = await service.restore_version(
        article_id,
        version,
        company_id=current_user.company_id,
        actor_role=current_user.role,
        actor_employee_id=current_user.id,
    )
    return article_response(article)


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
    return article_response(article)


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
        actor_employee_id=current_user.id,
    )
    return article_response(article)


@router.post(
    "/reindex-published",
    response_model=CorpusReindexResponse,
    summary="Reindex all current published knowledge articles",
    description=(
        "Rebuild derived pgvector chunks for every current published article "
        "in the authenticated tenant. Required after an embedding model or "
        "dimension change. Tenant context is the JWT company only; a query "
        "company_id that does not match is treated as not found. Employee "
        "callers are forbidden. Super Admin has no access without impersonation."
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
        status.HTTP_503_SERVICE_UNAVAILABLE: ERROR_RESPONSES[
            status.HTTP_503_SERVICE_UNAVAILABLE
        ],
    },
)
async def reindex_published_corpus(
    current_user: HRUser,
    indexer: ChunkIndexerDep,
    company_id: Annotated[
        UUID | None,
        Query(
            description=(
                "Claimed tenant id. Must match the authenticated company when "
                "provided; never used as RLS authority."
            ),
        ),
    ] = None,
) -> CorpusReindexResponse:
    result = await indexer.reindex_published_corpus(
        actor_company_id=current_user.company_id,
        actor_employee_id=current_user.id,
        actor_role=current_user.role,
        claimed_company_id=company_id,
    )
    return CorpusReindexResponse(
        indexed_articles=result.indexed_articles,
        indexed_chunks=result.indexed_chunks,
    )


@router.post(
    "/{article_id}/reindex",
    response_model=ArticleResponse,
    summary="Reindex a published knowledge article",
    description=(
        "Idempotent derived-index rebuild for the current published version. "
        "Tenant context is the authenticated company only; a query company_id "
        "that does not match is treated as not found. Draft and archived "
        "articles cannot be indexed. Historical chunks of other versions are "
        "not mutated."
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
        status.HTTP_503_SERVICE_UNAVAILABLE: ERROR_RESPONSES[
            status.HTTP_503_SERVICE_UNAVAILABLE
        ],
    },
)
async def reindex_article(
    article_id: UUID,
    current_user: HRUser,
    service: ArticleServiceDep,
    indexer: ChunkIndexerDep,
    company_id: Annotated[
        UUID | None,
        Query(
            description=(
                "Claimed tenant id. Must match the authenticated company when "
                "provided; never used as RLS authority."
            ),
        ),
    ] = None,
    version_id: Annotated[
        UUID | None,
        Query(
            description=(
                "Version to index. Must be the article's current published "
                "version when provided."
            ),
        ),
    ] = None,
) -> ArticleResponse:
    actor_company_id = current_user.company_id
    resolved_version_id = version_id
    if resolved_version_id is None:
        article = await service.get_article(
            article_id,
            company_id=actor_company_id,
            actor_role=current_user.role,
        )
        resolved_version_id = article.current_version_id
        if resolved_version_id is None:
            raise ValidationError(
                f"Cannot index article {article_id} without a current version"
            )
    await indexer.index_published_version(
        actor_company_id=actor_company_id,
        article_id=article_id,
        version_id=resolved_version_id,
        company_id=company_id,
    )
    loaded = await service.get_article(
        article_id,
        company_id=actor_company_id,
        actor_role=current_user.role,
    )
    return article_response(loaded)


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
        actor_employee_id=current_user.id,
    )
    return article_response(article)
