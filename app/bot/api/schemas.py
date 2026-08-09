from __future__ import annotations

from datetime import datetime
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


class AssignmentDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    company_id: UUID
    employee_id: UUID
    program_id: UUID
    status: str
    assigned_at: datetime


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


class ProgressItemDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    assignment_id: UUID
    step_id: UUID
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    step: ProgressStepDTO | None = None


class AssignmentProgressDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    percentage: float
    items: list[ProgressItemDTO]
