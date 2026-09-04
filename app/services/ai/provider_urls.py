"""Safe URL joining for LLM provider endpoints. Never logs secrets."""

from __future__ import annotations

from app.core.ai_constants import (
    ANTHROPIC_MESSAGES_URL,
    GEMINI_GENERATE_CONTENT_URL,
    OPENAI_CHAT_COMPLETIONS_URL,
)
from app.core.exceptions import ValidationError


def _require_http_url(value: str, *, field: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationError(f"{field} is required")
    if not (stripped.startswith("https://") or stripped.startswith("http://")):
        raise ValidationError(f"{field} must be an http(s) URL")
    return stripped.rstrip("/")


def join_chat_completions_url(base_url: str) -> str:
    """Append /chat/completions unless the caller already supplied that path.

    Does not invent a /v1 prefix. Configure the compatible API root, for example:
    ``https://example.test/compatible-mode/v1``.
    """
    root = _require_http_url(base_url, field="AI_LLM_BASE_URL")
    if root.endswith("/chat/completions"):
        return root
    return f"{root}/chat/completions"


def openai_chat_completions_url(base_url: str) -> str:
    if not base_url.strip():
        return OPENAI_CHAT_COMPLETIONS_URL
    return join_chat_completions_url(base_url)


def anthropic_messages_url(base_url: str) -> str:
    if not base_url.strip():
        return ANTHROPIC_MESSAGES_URL
    root = _require_http_url(base_url, field="AI_LLM_BASE_URL")
    if root.endswith("/messages"):
        return root
    return f"{root}/messages"


def gemini_generate_content_url(model: str, *, base_url: str = "") -> str:
    resolved_model = model.strip()
    if not resolved_model:
        raise ValidationError("AI_LLM_MODEL must not be empty")
    if not base_url.strip():
        return GEMINI_GENERATE_CONTENT_URL.format(model=resolved_model)
    root = _require_http_url(base_url, field="AI_LLM_BASE_URL")
    if root.endswith(":generateContent"):
        return root
    return f"{root}/models/{resolved_model}:generateContent"
