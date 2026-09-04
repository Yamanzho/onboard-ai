from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.db.assignment_rules import is_assignment_overdue
from app.db.enums import AssignmentPriority, AssignmentType

AssignmentPriorityLiteral = Literal["normal", "important", "critical"]
AssignmentTypeLiteral = Literal["program", "acknowledgement"]


class AcknowledgementDocumentInput(BaseModel):
    """HR-selected article; backend binds the current published version."""

    article_id: UUID
    position: int = Field(ge=1, description="Manual document order, starting at 1.")
    is_required: bool = True


class AssignmentCreate(BaseModel):
    """Assign a published program or acknowledgement package to employees.

    Legacy clients omit ``assignment_type`` and send ``employee_id`` + ``program_id``.
    Acknowledgement clients send ``assignment_type=acknowledgement`` and ``documents``.
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

    assignment_type: AssignmentTypeLiteral = Field(
        default=AssignmentType.PROGRAM.value,
        description="program (default) or acknowledgement.",
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
    program_id: UUID | None = Field(
        default=None,
        description="Published onboarding program. Required for program assignments.",
    )
    documents: list[AcknowledgementDocumentInput] = Field(
        default_factory=list,
        max_length=50,
        description="Documents for acknowledgement assignments. Order is manual.",
    )
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
        if self.assignment_type == AssignmentType.PROGRAM.value:
            if self.program_id is None:
                raise ValueError("program_id is required for program assignments")
            if self.documents:
                raise ValueError("documents are only valid for acknowledgement assignments")
        elif self.assignment_type == AssignmentType.ACKNOWLEDGEMENT.value:
            if self.program_id is not None:
                raise ValueError("program_id must be omitted for acknowledgement assignments")
            if not self.documents:
                raise ValueError("documents are required for acknowledgement assignments")
            positions = [item.position for item in self.documents]
            if len(positions) != len(set(positions)):
                raise ValueError("document positions must be unique")
            article_ids = [item.article_id for item in self.documents]
            if len(article_ids) != len(set(article_ids)):
                raise ValueError("duplicate articles are not allowed in one assignment")
        return self

    @property
    def is_legacy_single(self) -> bool:
        return (
            self.employee_id is not None
            and not self.employee_ids
            and not self.department_ids
        )


class AcknowledgementSummary(BaseModel):
    """Compact acknowledgement status for assignment list/detail."""

    total_documents: int
    required_documents: int
    acknowledged_required_count: int
    completed: bool
    title: str | None = None
    percentage: float = 0


class AssignmentResponse(BaseModel):
    """Assignment resource."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    employee_id: UUID
    assignment_type: str = AssignmentType.PROGRAM.value
    program_id: UUID | None = None
    assigned_by_id: UUID | None
    status: str
    priority: str = AssignmentPriority.NORMAL.value
    source_batch_id: UUID | None = None
    program_revision: int = Field(
        default=1,
        description="Course revision captured at assignment creation.",
    )
    structure_snapshot: dict[str, Any] | None = Field(
        default=None,
        exclude=True,
        description="Internal assignment-time course snapshot; not serialized.",
    )
    assigned_at: datetime
    due_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    acknowledgement: AcknowledgementSummary | None = None

    @computed_field
    @property
    def overdue(self) -> bool:
        return is_assignment_overdue(self.due_at, self.status)

    @computed_field
    @property
    def has_structure_snapshot(self) -> bool:
        snapshot = self.structure_snapshot
        return isinstance(snapshot, dict) and bool(snapshot.get("steps"))


class AssignmentBulkCreateResponse(BaseModel):
    """Result of a bulk assignment create (atomic)."""

    items: list[AssignmentResponse]
    source_batch_id: UUID | None = None
    count: int = 0


class AcknowledgementItemResponse(BaseModel):
    """Acknowledgement item metadata without document body."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assignment_id: UUID
    article_id: UUID
    article_version_id: UUID
    position: int
    is_required: bool
    acknowledged_at: datetime | None
    title: str
    version: int
    body_format: str


class AcknowledgementItemListResponse(BaseModel):
    items: list[AcknowledgementItemResponse]
    assignment_id: UUID
    assignment_status: str
    acknowledgement: AcknowledgementSummary


class AcknowledgementDocumentView(BaseModel):
    """Exact assigned KnowledgeArticleVersion content."""

    item: AcknowledgementItemResponse
    body: str
    assignment_status: str


class AcknowledgementActionResponse(BaseModel):
    item: AcknowledgementItemResponse
    assignment_status: str
    acknowledgement: AcknowledgementSummary
