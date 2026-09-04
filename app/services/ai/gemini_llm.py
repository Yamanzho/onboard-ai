"""Gemini generateContent adapter. No SDK. Key never logged."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.ai_constants import (
    DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.core.request_id import request_id_log_value
from app.services.ai.llm import LLMResult, _require_prompt, parse_llm_text
from app.services.ai.openai_http import ProviderFailure, post_openai_json
from app.services.ai.provider_urls import gemini_generate_content_url

logger = logging.getLogger("app.kb.llm")

HttpPost = Callable[[str, dict[str, str], dict[str, Any]], Awaitable[dict[str, Any]]]


class GeminiLLMProvider:
    """Hosted text generation via Gemini generateContent (httpx, no SDK)."""

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
            raise ValidationError("Gemini LLM API key is required")
        resolved_model = model.strip()
        if not resolved_model:
            raise ValidationError("Gemini LLM model is required")
        self._api_key = key
        self._model = resolved_model
        self._timeout = timeout_seconds
        self._url = gemini_generate_content_url(resolved_model, base_url=base_url)
        self._max_output_tokens = max_output_tokens
        self._http_post = http_post

    @property
    def model(self) -> str:
        return self._model

    def __repr__(self) -> str:
        return f"GeminiLLMProvider(model={self._model!r})"

    async def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResult:
        system = _require_prompt(system_prompt, field="system_prompt")
        user = _require_prompt(user_prompt, field="user_prompt")
        started = time.perf_counter()
        try:
            body = await self._post(
                {
                    "system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": self._max_output_tokens,
                    },
                }
            )
        except (ValidationError, ServiceUnavailableError):
            logger.info(
                "kb_llm_gemini request_id=%s model=%s result=error duration_ms=%.1f",
                request_id_log_value(),
                self._model,
                (time.perf_counter() - started) * 1000,
            )
            raise
        text = _parse_gemini_text(body)
        logger.info(
            "kb_llm_gemini request_id=%s model=%s result=success duration_ms=%.1f",
            request_id_log_value(),
            self._model,
            (time.perf_counter() - started) * 1000,
        )
        return parse_llm_text(text)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-goog-api-key": self._api_key,
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
                provider="gemini",
            )
        except ProviderFailure as exc:
            exc.reraise_app()
            raise AssertionError("unreachable") from exc


def _parse_gemini_text(body: dict[str, Any]) -> str:
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValidationError("LLM provider returned an invalid completion")
    first = candidates[0]
    if not isinstance(first, dict):
        raise ValidationError("LLM provider returned an invalid completion")
    content = first.get("content")
    if not isinstance(content, dict):
        raise ValidationError("LLM provider returned an invalid completion")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValidationError("LLM provider returned an invalid completion")
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)
    joined = "".join(texts).strip()
    if not joined:
        raise ValidationError("LLM provider returned an invalid completion")
    return joined
