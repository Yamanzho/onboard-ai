from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.ai.embedding_identity import (
    EmbeddingIdentity,
    active_embedding_identity,
    version_embedding_compatibility,
)

KnowledgeIndexStatusLiteral = Literal["pending", "indexing", "indexed", "failed"]
EmbeddingCompatibilityReason = Literal[
    "provider_changed",
    "model_changed",
    "dimension_changed",
    "metadata_missing",
    "not_indexed",
]


class ArticleVersionResponse(BaseModel):
    """Immutable content snapshot for a knowledge article."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    version: int = Field(description="Monotonic version number starting at 1.")
    title: str
    body: str
    body_format: str
    change_summary: str | None = None
    created_by_id: UUID | None = None
    published_at: datetime | None = None
    index_status: KnowledgeIndexStatusLiteral
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    indexed_chunk_count: int | None = None
    indexing_started_at: datetime | None = None
    indexed_at: datetime | None = None
    indexing_failed_at: datetime | None = None
    failure_category: str | None = None
    indexing_in_progress: bool
    index_stale: bool
    embedding_compatible: bool = False
    reindex_required: bool = True
    embedding_incompatibility_reason: EmbeddingCompatibilityReason | None = None
    created_at: datetime
    updated_at: datetime


class ArticleVersionSummary(BaseModel):
    """Version metadata without body (history list)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    version: int
    title: str
    change_summary: str | None = None
    created_by_id: UUID | None = None
    published_at: datetime | None = None
    index_status: KnowledgeIndexStatusLiteral
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    indexed_chunk_count: int | None = None
    indexing_started_at: datetime | None = None
    indexed_at: datetime | None = None
    indexing_failed_at: datetime | None = None
    failure_category: str | None = None
    indexing_in_progress: bool
    index_stale: bool
    embedding_compatible: bool = False
    reindex_required: bool = True
    embedding_incompatibility_reason: EmbeddingCompatibilityReason | None = None
    created_at: datetime


class ArticleVersionListResponse(BaseModel):
    items: list[ArticleVersionSummary]


def article_version_response(
    version: object,
    *,
    active: EmbeddingIdentity | None = None,
) -> ArticleVersionResponse:
    compatibility = version_embedding_compatibility(
        version,
        active=active or active_embedding_identity(),
    )
    return ArticleVersionResponse.model_validate(version).model_copy(
        update={
            "embedding_compatible": compatibility.compatible,
            "reindex_required": compatibility.reindex_required,
            "embedding_incompatibility_reason": compatibility.reason,
        }
    )


def article_version_summary(
    version: object,
    *,
    active: EmbeddingIdentity | None = None,
) -> ArticleVersionSummary:
    compatibility = version_embedding_compatibility(
        version,
        active=active or active_embedding_identity(),
    )
    return ArticleVersionSummary.model_validate(version).model_copy(
        update={
            "embedding_compatible": compatibility.compatible,
            "reindex_required": compatibility.reindex_required,
            "embedding_incompatibility_reason": compatibility.reason,
        }
    )
