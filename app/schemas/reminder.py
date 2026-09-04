from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReminderModeLiteral = Literal["default", "reduced", "disabled"]
OutboundStatusLiteral = Literal["pending", "sending", "sent", "failed"]
AssignmentOutboundKind = Literal[
    "assignment_initial",
    "assignment_reminder",
    "assignment_manual_reminder",
]


class ReminderPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mode: ReminderModeLiteral
    acknowledged_until_date: date | None = None
    last_acknowledged_at: datetime | None = None
    last_automated_reminder_at: datetime | None = None
    last_manual_reminder_at: datetime | None = None
    updated_by_employee_at: datetime | None = None
    updated_at: datetime | None = None


class AssignmentNotificationItem(BaseModel):
    id: UUID
    source_type: AssignmentOutboundKind
    created_at: datetime
    sent_at: datetime | None = None
    status: OutboundStatusLiteral
    preview: str
    last_error_category: str | None = None


class AssignmentNotificationsResponse(BaseModel):
    assignment_id: UUID
    program_title: str
    preference: ReminderPreferenceResponse
    items: list[AssignmentNotificationItem]


class RemindNowResponse(BaseModel):
    enqueued: bool
    outbound_id: UUID | None = None
    status: OutboundStatusLiteral | None = None
    cooldown_seconds: int = Field(default=600)


class ReminderScanResponse(BaseModel):
    scanned: int
    enqueued: int


class AssignmentOutboundAllowResponse(BaseModel):
    allowed: bool
