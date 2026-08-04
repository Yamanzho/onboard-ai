from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.knowledge.tag import TagResponse
from app.schemas.knowledge.version import ArticleVersionResponse

KnowledgeStatusLiteral = Literal["draft", "published", "archived"]
KnowledgeVisibilityLiteral = Literal["company", "program"]
KnowledgeBodyFormatLiteral = Literal["markdown", "html", "plain"]


class ArticleCreate(BaseModel):
    """Payload for creating a draft knowledge article with version 1."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "company_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "title": "VPN setup",
                    "body": "Connect via the company VPN client.",
                    "body_format": "markdown",
                    "visibility": "company",
                    "tag_ids": [],
                }
            ]
        }
    )

    company_id: UUID = Field(description="Tenant company that owns the article.")
    title: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)
    body_format: KnowledgeBodyFormatLiteral = Field(default="markdown")
    category_id: UUID | None = Field(default=None)
    visibility: KnowledgeVisibilityLiteral = Field(default="company")
    tag_ids: list[UUID] = Field(
        default_factory=list,
        description="Existing tag IDs within the same company.",
    )
    change_summary: str | None = Field(default=None, max_length=2000)


class ArticleUpdate(BaseModel):
    """Update article metadata and/or content.

    Content fields create a new immutable version; previous versions are never mutated.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "VPN setup (updated)",
                    "body": "Use WireGuard from the IT portal.",
                    "change_summary": "Switched to WireGuard instructions",
                }
            ]
        }
    )

    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, min_length=1)
    body_format: KnowledgeBodyFormatLiteral | None = None
    category_id: UUID | None = None
    visibility: KnowledgeVisibilityLiteral | None = None
    tag_ids: list[UUID] | None = Field(
        default=None,
        description="When set, replaces the full tag set for the article.",
    )
    change_summary: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "ArticleUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class ArticleResponse(BaseModel):
    """Knowledge article with current version and tags."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    category_id: UUID | None
    current_version_id: UUID | None
    status: str
    visibility: str
    created_by_id: UUID | None
    current_version: ArticleVersionResponse | None = None
    tags: list[TagResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ArticleListResponse(BaseModel):
    """Paginated-style list wrapper for knowledge articles."""

    items: list[ArticleResponse]
