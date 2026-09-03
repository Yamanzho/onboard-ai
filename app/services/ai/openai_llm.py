"""OpenAI Chat Completions LLM provider. No SDK. Key never logged."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.ai_constants import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    OPENAI_CHAT_COMPLETIONS_URL,
    OPENAI_LLM_MODEL,
)
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.core.request_id import request_id_log_value
from app.services.ai.llm import LLMResult, _require_prompt, parse_llm_text
from app.services.ai.openai_http import (
    ProviderFailure,
    post_openai_json,
    raise_as_app_error,
)

logger = logging.getLogger("app.kb.llm")

HttpPost = Callable[[str, dict[str, str], dict[str, Any]], Awaitable[dict[str, Any]]]


class OpenAILLMProvider:
    """Hosted text generation via OpenAI Chat Completions (httpx, no SDK).

    The model is not an authorization source. The API key must never appear in
    logs, exception messages, or generated text stored by this class.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = OPENAI_LLM_MODEL,
        timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        base_url: str = OPENAI_CHAT_COMPLETIONS_URL,
        http_post: HttpPost | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValidationError("OpenAI LLM API key is required")
        self._api_key = key
        self._model = model.strip() or OPENAI_LLM_MODEL
        self._timeout = timeout_seconds
        self._base_url = base_url
        self._http_post = http_post

    @property
    def model(self) -> str:
        return self._model

    def __repr__(self) -> str:
        return f"OpenAILLMProvider(model={self._model!r})"

    async def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResult:
        system = _require_prompt(system_prompt, field="system_prompt")
        user = _require_prompt(user_prompt, field="user_prompt")
        started = time.perf_counter()
        try:
            body = await self._post(
                {
                    "model": self._model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                }
            )
        except (ValidationError, ServiceUnavailableError):
            logger.info(
                "kb_llm_openai request_id=%s model=%s result=error duration_ms=%.1f",
                request_id_log_value(),
                self._model,
                (time.perf_counter() - started) * 1000,
            )
            raise
        text = _parse_chat_completion(body)
        logger.info(
            "kb_llm_openai request_id=%s model=%s result=success duration_ms=%.1f",
            request_id_log_value(),
            self._model,
            (time.perf_counter() - started) * 1000,
        )
        return parse_llm_text(text)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._http_post is not None:
            return await self._http_post(self._base_url, headers, payload)
        try:
            return await post_openai_json(
                self._base_url,
                headers,
                payload,
                timeout=self._timeout,
                kind="llm",
                model=self._model,
            )
        except ProviderFailure as exc:
            exc.reraise_app()
            raise AssertionError("unreachable") from exc


def _decode_openai_llm_response(response: httpx.Response) -> dict[str, Any]:
    return raise_as_app_error(response, kind="llm")


def _parse_chat_completion(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValidationError("LLM provider returned an invalid completion")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValidationError("LLM provider returned an invalid completion")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValidationError("LLM provider returned an invalid completion")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValidationError("LLM provider returned an invalid completion")
    return content
