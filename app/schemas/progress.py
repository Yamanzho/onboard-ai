from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.limits import (
    MAX_PROGRESS_PAYLOAD_JSON_BYTES,
    ensure_json_object_within_limit,
)


class ProgressCompleteRequest(BaseModel):
    """Optional payload stored when completing a progress row."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"payload": {"ack": True}}]}
    )

    payload: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional completion payload (quiz answers, ack metadata, etc.); "
            f"max {MAX_PROGRESS_PAYLOAD_JSON_BYTES} serialized UTF-8 bytes."
        ),
    )

    @field_validator("payload")
    @classmethod
    def limit_payload_size(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return value
        return ensure_json_object_within_limit(
            value,
            max_bytes=MAX_PROGRESS_PAYLOAD_JSON_BYTES,
            field_name="payload",
        )


class ProgressResponse(BaseModel):
    """Progress resource for a single assignment step."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assignment_id: UUID
    step_id: UUID
    status: str
    payload: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssignmentProgressResponse(BaseModel):
    """Progress list for an assignment plus completion percentage."""

    percentage: float = Field(description="Completion percentage (0-100).")
    items: list[ProgressResponse] = Field(description="Per-step progress rows.")
