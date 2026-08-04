from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
        description="Type-specific payload (text, quiz questions, links, etc.).",
    )
    is_required: bool = Field(default=True)
    estimated_minutes: int | None = Field(default=None, ge=0)


class StepUpdate(BaseModel):
    """Partial step update. Position must be changed via reorder endpoint."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    step_type: StepTypeLiteral | None = None
    content: dict[str, Any] | None = None
    is_required: bool | None = None
    estimated_minutes: int | None = Field(default=None, ge=0)

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
