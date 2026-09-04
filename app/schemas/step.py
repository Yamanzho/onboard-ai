from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.schemas.limits import (
    MAX_STEP_CONTENT_JSON_BYTES,
    ensure_json_object_within_limit,
)
from app.services.step_content import content_blocks_as_dicts

StepTypeLiteral = Literal["content", "task", "quiz", "ack"]


class StepCreate(BaseModel):
    """Payload for adding a step to a program."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "Read company handbook",
                    "step_type": "content",
                    "content": {"body": "Welcome!"},
                    "is_required": True,
                    "estimated_minutes": 15,
                }
            ]
        }
    )

    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    step_type: StepTypeLiteral = Field(
        default="content",
        description="Step behavior type for the bot/UI.",
    )
    position: int | None = Field(
        default=None,
        ge=0,
        description="Optional explicit order; defaults to append at the end.",
    )
    content: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Type-specific payload (text, quiz questions, links, etc.); "
            f"max {MAX_STEP_CONTENT_JSON_BYTES} serialized UTF-8 bytes."
        ),
    )
    is_required: bool = Field(default=True)
    estimated_minutes: int | None = Field(default=None, ge=0)

    @field_validator("content")
    @classmethod
    def limit_content_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        return ensure_json_object_within_limit(
            value,
            max_bytes=MAX_STEP_CONTENT_JSON_BYTES,
            field_name="content",
        )


class StepUpdate(BaseModel):
    """Partial step update. Position must be changed via reorder endpoint."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    step_type: StepTypeLiteral | None = None
    content: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Type-specific payload; "
            f"max {MAX_STEP_CONTENT_JSON_BYTES} serialized UTF-8 bytes."
        ),
    )
    is_required: bool | None = None
    estimated_minutes: int | None = Field(default=None, ge=0)

    @field_validator("content")
    @classmethod
    def limit_content_size(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return value
        return ensure_json_object_within_limit(
            value,
            max_bytes=MAX_STEP_CONTENT_JSON_BYTES,
            field_name="content",
        )

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "StepUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class StepReorderRequest(BaseModel):
    """New ordered list of all step IDs belonging to the program."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "step_ids": [
                        "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "3fa85f64-5717-4562-b3fc-2c963f66afa7",
                    ]
                }
            ]
        }
    )

    step_ids: list[UUID] = Field(
        ...,
        min_length=1,
        description="Complete ordered list of every step in the program.",
    )


class StepResponse(BaseModel):
    """Onboarding step resource."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    program_id: UUID
    title: str
    description: str | None
    step_type: str
    position: int
    content: dict[str, Any]
    is_required: bool
    estimated_minutes: int | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def content_blocks(self) -> list[dict[str, str]]:
        return content_blocks_as_dicts(self.content)

    @computed_field
    @property
    def block_count(self) -> int:
        return len(self.content_blocks)
