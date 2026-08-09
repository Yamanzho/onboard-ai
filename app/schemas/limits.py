"""Explicit payload size limits for authenticated write schemas (SEC-M6).

Chosen from current product usage (KB textarea articles, step content.body /
quizzes, tiny progress ack payloads, company locale/flags) — generous for
legitimate content, tight enough to block multi-megabyte DoS dumps.
"""

from __future__ import annotations

import json
from typing import Any

# Knowledge article body (markdown/html/plain). ~200k characters ≈ 200 KiB
# of typical UTF-8 text — enough for long SOPs with code blocks; rejects
# multi-megabyte dumps. Aligns above program description (5k) / change_summary (2k).
MAX_ARTICLE_BODY_LENGTH = 200_000

# Onboarding step JSON content ({body}, quiz questions, links, etc.).
# Frontend primarily stores content.body; 64 KiB covers large quizzes.
MAX_STEP_CONTENT_JSON_BYTES = 64_000

# Progress completion payload (quiz answers, ack metadata). Typically tiny.
MAX_PROGRESS_PAYLOAD_JSON_BYTES = 16_384

# Company settings JSON (locale, feature flags). Not a document store.
MAX_COMPANY_SETTINGS_JSON_BYTES = 16_384


def ensure_json_object_within_limit(
    value: dict[str, Any],
    *,
    max_bytes: int,
    field_name: str,
) -> dict[str, Any]:
    """Reject dict payloads whose compact UTF-8 JSON exceeds ``max_bytes``."""
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError(
            f"{field_name} exceeds maximum serialized size of {max_bytes} bytes"
        )
    return value
