"""Provider-independent LLM interface. Not an authorization source.

Dev/CI: ``FakeLLMProvider`` (in-process, no network).
Production hosted: ``OpenAILLMProvider`` (Chat Completions via httpx, no SDK).

API keys must never be logged. The LLM must not be treated as ACL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.ai_constants import (
    NO_ANSWER_TOKEN,
    OPENAI_LLM_MODEL,
    SUPPORTED_LLM_PROVIDERS,
)
from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class LLMResult:
    """Raw model text. Citations are assigned by the application, not the model."""

    text: str
    no_answer: bool


@runtime_checkable
class LLMProvider(Protocol):
    """Turn a system + user prompt into text. Not an authorization source."""

    @property
    def model(self) -> str:
        """Configured model name."""
        ...

    async def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResult:
        """Generate a completion. Empty prompts are rejected."""
        ...


def _require_prompt(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    if not value.strip():
        raise ValidationError(f"{field} must not be empty")
    return value


def parse_llm_text(text: str) -> LLMResult:
    stripped = text.strip()
    if not stripped:
        raise ValidationError("LLM returned an empty completion")
    token = NO_ANSWER_TOKEN
    if stripped == token or stripped.startswith(f"{token}\n") or stripped.startswith(f"{token} "):
        return LLMResult(text=stripped, no_answer=True)
    return LLMResult(text=stripped, no_answer=False)


class FakeLLMProvider:
    """Deterministic in-process LLM. Never calls the network.

    Answers only from ``<source id="Sn">`` blocks in the user prompt. The
    question is untrusted data and is never copied into the answer. Prompt
    injection in the question or in KB text cannot invent extra sources.
    """

    def __init__(self, *, model: str = "fake-llm", force_no_answer: bool = False) -> None:
        self._model = model.strip() or "fake-llm"
        self._force_no_answer = force_no_answer

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResult:
        _require_prompt(system_prompt, field="system_prompt")
        user = _require_prompt(user_prompt, field="user_prompt")
        if self._force_no_answer:
            return LLMResult(text=NO_ANSWER_TOKEN, no_answer=True)
        source_ids = _source_ids_from_prompt(user)
        if not source_ids:
            return LLMResult(text=NO_ANSWER_TOKEN, no_answer=True)
        cited = source_ids[0]
        return LLMResult(
            text=f"According to the knowledge base [{cited}].",
            no_answer=False,
        )


def _source_ids_from_prompt(user_prompt: str) -> tuple[str, ...]:
    ids: list[str] = []
    needle = '<source id="'
    start = 0
    while True:
        index = user_prompt.find(needle, start)
        if index < 0:
            break
        begin = index + len(needle)
        end = user_prompt.find('"', begin)
        if end < 0:
            break
        source_id = user_prompt[begin:end]
        if source_id and source_id not in ids:
            ids.append(source_id)
        start = end + 1
    return tuple(ids)


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Return the configured LLM provider. Unknown providers fail closed."""
    resolved = settings or get_settings()
    provider = resolved.ai_llm_provider.strip().lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise ValidationError(f"Unsupported LLM provider {resolved.ai_llm_provider!r}")
    if provider == "fake":
        return FakeLLMProvider(model=resolved.ai_llm_model.strip() or "fake-llm")
    if provider == "openai":
        from app.services.ai.openai_llm import OpenAILLMProvider

        return OpenAILLMProvider(
            api_key=resolved.ai_llm_api_key.get_secret_value(),
            model=resolved.ai_llm_model.strip() or OPENAI_LLM_MODEL,
            timeout_seconds=resolved.ai_llm_timeout_seconds,
        )
    raise ValidationError(f"Unsupported LLM provider {resolved.ai_llm_provider!r}")
