from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.schemas.limits import (
    MAX_PROGRESS_PAYLOAD_JSON_BYTES,
    ensure_json_object_within_limit,
)
from app.services.step_content import content_blocks_as_dicts, payload_block_index


class ProgressAdvanceRequest(BaseModel):
    """Idempotent content-block navigation."""

    expected_block_index: int = Field(ge=0)


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


class ProgressStepInfo(BaseModel):
    """Step payload embedded in assignment progress (for bot / employee clients)."""

    model_config = ConfigDict(from_attributes=True)

    title: str
    description: str | None = None
    step_type: str
    content: dict[str, Any] = Field(default_factory=dict)
    position: int

    @computed_field
    @property
    def content_blocks(self) -> list[dict[str, str]]:
        return content_blocks_as_dicts(self.content)

    @computed_field
    @property
    def block_count(self) -> int:
        return len(self.content_blocks)


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
    step: ProgressStepInfo | None = None

    @computed_field
    @property
    def block_index(self) -> int | None:
        """Current content-block cursor from payload, if the client stored one."""
        return payload_block_index(self.payload)


class AssignmentProgressResponse(BaseModel):
    """Progress list for an assignment plus completion percentage."""

    percentage: float = Field(description="Completion percentage (0-100).")
    items: list[ProgressResponse] = Field(description="Per-step progress rows.")
    program_id: UUID | None = None
    assignment_status: str | None = None
