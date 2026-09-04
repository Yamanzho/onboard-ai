from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EmployeeDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    company_id: UUID
    telegram_user_id: int
    full_name: str
    role: str
    status: str
    email: str | None = None
    telegram_username: str | None = None
    telegram_connected: bool = False
    company_name: str | None = None
    company_description: str | None = None
    hired_at: date | None = None


class AssignmentDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    company_id: UUID
    employee_id: UUID
    program_id: UUID
    status: str
    assigned_at: datetime
    due_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    priority: str = "normal"


class ProgramDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    company_id: UUID
    title: str
    description: str | None = None
    is_active: bool


class ProgressStepDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    description: str | None = None
    step_type: str = "content"
    content: dict[str, Any] = Field(default_factory=dict)
    position: int = 0
    content_blocks: list[dict[str, str]] = Field(default_factory=list)
    block_count: int = 0


class ProgressItemDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    assignment_id: UUID
    step_id: UUID
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    block_index: int | None = None
    step: ProgressStepDTO | None = None


class AssignmentProgressDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    percentage: float
    items: list[ProgressItemDTO]
    program_id: UUID | None = None
    assignment_status: str | None = None
