"""Public AI chat HTTP schemas. Identity is never accepted from the client."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.ai_constants import MAX_CHAT_QUESTION_CHARS


class AIChatRequest(BaseModel):
    """Employee-facing knowledge-base question, optionally continuing a thread."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"message": "How do I get VPN access?"},
                {
                    "message": "Who should I write to?",
                    "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                },
            ]
        },
    )

    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_CHAT_QUESTION_CHARS,
        description="Question in the employee's language (RU, KK, or EN).",
    )
    conversation_id: UUID | None = Field(
        default=None,
        description=(
            "Optional conversation to continue. If omitted, a new conversation "
            "is created for the authenticated employee. The id is an identifier "
            "only; ownership is always taken from the authenticated session."
        ),
    )

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be empty")
        if len(stripped) > MAX_CHAT_QUESTION_CHARS:
            raise ValueError(
                f"message must be at most {MAX_CHAT_QUESTION_CHARS} characters"
            )
        return stripped


class AIChatCitation(BaseModel):
    """Public citation for a knowledge-base excerpt supplied to the model."""

    source_id: str = Field(description="Deterministic context id such as S1.")
    title: str = Field(description="Knowledge article title.")
    article_id: UUID = Field(
        description="Article id (same identifier as GET /knowledge/articles/{id}).",
    )


class AIChatResponse(BaseModel):
    """Structured RAG answer. no_answer is a normal 200, not HTTP 404."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "answer": "Use the company VPN client from the IT portal. [S1]",
                    "no_answer": False,
                    "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "citations": [
                        {
                            "source_id": "S1",
                            "title": "VPN Access Policy",
                            "article_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        }
                    ],
                }
            ]
        }
    )

    answer: str
    no_answer: bool
    conversation_id: UUID
    citations: list[AIChatCitation] = Field(default_factory=list)


class AIConversationSummary(BaseModel):
    """List-row metadata. Tenant and employee ids are never exposed."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None = None
    message_count: int = 0


class AIConversationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AIConversationSummary]


class AIConversationMessage(BaseModel):
    """One persisted turn. Citations reconstruct the existing chat UI only."""

    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    role: str
    content: str
    created_at: datetime
    citations: list[AIChatCitation] = Field(default_factory=list)
    no_answer: bool = False


class AIConversationDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[AIConversationMessage]
