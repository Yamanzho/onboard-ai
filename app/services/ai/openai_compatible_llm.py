"""OpenAI-compatible Chat Completions adapter (Qwen / Model Studio, etc.)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.ai_constants import DEFAULT_LLM_TIMEOUT_SECONDS
from app.core.exceptions import ValidationError
from app.services.ai.openai_llm import OpenAILLMProvider
from app.services.ai.provider_urls import join_chat_completions_url

HttpPost = Callable[[str, dict[str, str], dict[str, Any]], Awaitable[dict[str, Any]]]


class OpenAICompatibleLLMProvider(OpenAILLMProvider):
    """Same Chat Completions protocol as OpenAI, caller-supplied API root.

    ``base_url`` is the compatible API root (for example
    ``https://example.test/compatible-mode/v1``). The adapter POSTs
    ``{base_url}/chat/completions`` and does not invent a ``/v1`` prefix.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        http_post: HttpPost | None = None,
    ) -> None:
        resolved_model = model.strip()
        if not resolved_model:
            raise ValidationError("OpenAI-compatible LLM model is required")
        super().__init__(
            api_key=api_key,
            model=resolved_model,
            timeout_seconds=timeout_seconds,
            base_url=join_chat_completions_url(base_url),
            http_post=http_post,
            provider="openai_compatible",
        )

    def __repr__(self) -> str:
        return f"OpenAICompatibleLLMProvider(model={self._model!r})"
