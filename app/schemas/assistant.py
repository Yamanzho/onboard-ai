"""Phase 9I orchestrated assistant HTTP schemas."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ai import AIChatCitation, AIChatRequest


class AssistantAssignmentRef(BaseModel):
    id: UUID
    title: str
    assignment_type: str


class AssistantChatRequest(AIChatRequest):
    """Same body as /ai/chat: message + optional conversation_id."""


class AssistantChatResponse(BaseModel):
    """Unified assistant payload. Telegram uses action, not prose, for UI."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(description="User-facing text (also used by Telegram formatter).")
    text: str
    no_answer: bool = False
    intent: str
    kind: str
    action: str = "none"
    assignment_ids: list[UUID] = Field(default_factory=list)
    assignments: list[AssistantAssignmentRef] = Field(default_factory=list)
    conversation_id: UUID | None = None
    citations: list[AIChatCitation] = Field(default_factory=list)
    used_retriever: bool = False
    used_llm: bool = False
