from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssignmentCreate(BaseModel):
    """Assign a published program to an employee."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "employee_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "program_id": "3fa85f64-5717-4562-b3fc-2c963f66afa7",
                    "assigned_by_id": None,
                    "due_at": None,
                }
            ]
        }
    )

    employee_id: UUID = Field(description="Employee receiving the program.")
    program_id: UUID = Field(description="Published onboarding program to assign.")
    assigned_by_id: UUID | None = Field(
        default=None,
        description="Optional HR/admin employee who created the assignment.",
    )
    due_at: datetime | None = Field(
        default=None,
        description="Optional deadline for completing the assignment.",
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
    assigned_at: datetime
    due_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
