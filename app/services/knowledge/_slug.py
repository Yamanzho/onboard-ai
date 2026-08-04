"""Shared helpers for knowledge services."""

from __future__ import annotations

import re
import unicodedata

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, max_length: int = 128) -> str:
    """Normalize a display name into a URL-safe slug."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_RE.sub("-", ascii_text.lower()).strip("-")
    if not slug:
        raise ValueError("Unable to derive a slug from the provided name")
    return slug[:max_length].rstrip("-")
