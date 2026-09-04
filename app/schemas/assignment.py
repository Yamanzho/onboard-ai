from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.db.assignment_rules import is_assignment_overdue
from app.db.enums import AssignmentPriority

AssignmentPriorityLiteral = Literal["normal", "important", "critical"]


class AssignmentCreate(BaseModel):
    """Assign a published program to one or more employees.

    Legacy clients send ``employee_id`` alone and receive a single assignment.
    Bulk clients send ``employee_ids`` and/or ``department_ids``.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "employee_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "program_id": "3fa85f64-5717-4562-b3fc-2c963f66afa7",
                    "assigned_by_id": None,
                    "due_at": None,
                    "priority": "normal",
                }
            ]
        }
    )

    employee_id: UUID | None = Field(
        default=None,
        description="Single employee (legacy). Do not combine with employee_ids.",
    )
    employee_ids: list[UUID] = Field(
        default_factory=list,
        max_length=1000,
        description="Employees to assign. Deduplicated with department members.",
    )
    department_ids: list[UUID] = Field(
        default_factory=list,
        max_length=1000,
        description="Active departments whose current members are assigned (snapshot).",
    )
    program_id: UUID = Field(description="Published onboarding program to assign.")
    assigned_by_id: UUID | None = Field(
        default=None,
        description="Optional HR/admin employee who created the assignment.",
    )
    due_at: datetime | None = Field(
        default=None,
        description="Default deadline applied unless a per-employee override is set.",
    )
    priority: AssignmentPriorityLiteral = Field(
        default=AssignmentPriority.NORMAL.value,
        description="Assignment priority: normal, important, or critical.",
    )
    deadline_overrides: dict[UUID, datetime | None] = Field(
        default_factory=dict,
        description="Per-employee due_at overrides keyed by employee UUID.",
    )

    @model_validator(mode="after")
    def require_recipients_and_disambiguate(self) -> Self:
        if self.employee_id is not None and self.employee_ids:
            raise ValueError("Provide employee_id or employee_ids, not both")
        if (
            self.employee_id is None
            and not self.employee_ids
            and not self.department_ids
        ):
            raise ValueError(
                "At least one of employee_id, employee_ids, or department_ids is required"
            )
        return self

    @property
    def is_legacy_single(self) -> bool:
        return (
            self.employee_id is not None
            and not self.employee_ids
            and not self.department_ids
        )


class AssignmentResponse(BaseModel):
    """Assignment resource."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    employee_id: UUID
    program_id: UUID
    assigned_by_id: UUID | None
    status: str
    priority: str = AssignmentPriority.NORMAL.value
    source_batch_id: UUID | None = None
    assigned_at: datetime
    due_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def overdue(self) -> bool:
        return is_assignment_overdue(self.due_at, self.status)


class AssignmentBulkCreateResponse(BaseModel):
    """Result of a bulk assignment create (atomic)."""

    items: list[AssignmentResponse]
    source_batch_id: UUID | None = None
    count: int = 0
