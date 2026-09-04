from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AcknowledgementSummaryDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_documents: int = 0
    required_documents: int = 0
    acknowledged_required_count: int = 0
    completed: bool = False
    title: str | None = None
    percentage: float = 0


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
    assignment_type: str = "program"
    program_id: UUID | None = None
    status: str
    assigned_at: datetime
    due_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    priority: str = "normal"
    acknowledgement: AcknowledgementSummaryDTO | None = None


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


class AcknowledgementItemDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    assignment_id: UUID
    article_id: UUID
    article_version_id: UUID
    position: int
    is_required: bool
    acknowledged_at: datetime | None = None
    title: str = ""
    version: int = 0
    body_format: str = "markdown"


class AcknowledgementListDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[AcknowledgementItemDTO]
    assignment_id: UUID
    assignment_status: str
    acknowledgement: AcknowledgementSummaryDTO


class AcknowledgementDocumentDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item: AcknowledgementItemDTO
    body: str
    assignment_status: str


class AcknowledgementActionDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item: AcknowledgementItemDTO
    assignment_status: str
    acknowledgement: AcknowledgementSummaryDTO
