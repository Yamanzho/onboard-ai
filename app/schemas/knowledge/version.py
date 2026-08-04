from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime
    updated_at: datetime
