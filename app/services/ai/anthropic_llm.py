"""Anthropic Messages API adapter. No SDK. Key never logged."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.ai_constants import (
    ANTHROPIC_API_VERSION,
    DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.core.request_id import request_id_log_value
from app.services.ai.llm import LLMResult, _require_prompt, parse_llm_text
from app.services.ai.openai_http import ProviderFailure, post_openai_json
from app.services.ai.provider_urls import anthropic_messages_url

logger = logging.getLogger("app.kb.llm")

HttpPost = Callable[[str, dict[str, str], dict[str, Any]], Awaitable[dict[str, Any]]]


class AnthropicLLMProvider:
    """Hosted text generation via Anthropic Messages (httpx, no SDK)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        base_url: str = "",
        max_output_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS,
        http_post: HttpPost | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValidationError("Anthropic LLM API key is required")
        resolved_model = model.strip()
        if not resolved_model:
            raise ValidationError("Anthropic LLM model is required")
        self._api_key = key
        self._model = resolved_model
        self._timeout = timeout_seconds
        self._url = anthropic_messages_url(base_url)
        self._max_output_tokens = max_output_tokens
        self._http_post = http_post

    @property
    def model(self) -> str:
        return self._model

    def __repr__(self) -> str:
        return f"AnthropicLLMProvider(model={self._model!r})"

    async def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResult:
        system = _require_prompt(system_prompt, field="system_prompt")
        user = _require_prompt(user_prompt, field="user_prompt")
        started = time.perf_counter()
        try:
            body = await self._post(
                {
                    "model": self._model,
                    "max_tokens": self._max_output_tokens,
                    "temperature": 0,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                }
            )
        except (ValidationError, ServiceUnavailableError):
            logger.info(
                "kb_llm_anthropic request_id=%s model=%s result=error duration_ms=%.1f",
                request_id_log_value(),
                self._model,
                (time.perf_counter() - started) * 1000,
            )
            raise
        text = _parse_anthropic_text(body)
        logger.info(
            "kb_llm_anthropic request_id=%s model=%s result=success duration_ms=%.1f",
            request_id_log_value(),
            self._model,
            (time.perf_counter() - started) * 1000,
        )
        return parse_llm_text(text)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }
        if self._http_post is not None:
            return await self._http_post(self._url, headers, payload)
        try:
            return await post_openai_json(
                self._url,
                headers,
                payload,
                timeout=self._timeout,
                kind="llm",
                model=self._model,
                provider="anthropic",
            )
        except ProviderFailure as exc:
            exc.reraise_app()
            raise AssertionError("unreachable") from exc


def _parse_anthropic_text(body: dict[str, Any]) -> str:
    blocks = body.get("content")
    if not isinstance(blocks, list) or not blocks:
        raise ValidationError("LLM provider returned an invalid completion")
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in {None, "text"}:
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    joined = "".join(parts).strip()
    if not joined:
        raise ValidationError("LLM provider returned an invalid completion")
    return joined
