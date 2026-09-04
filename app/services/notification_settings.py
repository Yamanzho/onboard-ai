"""Typed helpers for Company.settings['notifications'] JSONB."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import ValidationError

DEFAULT_WINDOW_START = time(9, 0)
DEFAULT_WINDOW_END = time(18, 0)


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    window_start: time = DEFAULT_WINDOW_START
    window_end: time = DEFAULT_WINDOW_END
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None


def resolve_timezone(name: str | None) -> ZoneInfo:
    raw = (name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return ZoneInfo("UTC")


def parse_hhmm(raw: Any, *, field_name: str) -> time:
    if not isinstance(raw, str):
        raise ValidationError(f"{field_name} must be HH:MM")
    parts = raw.strip().split(":")
    if len(parts) != 2:
        raise ValidationError(f"{field_name} must be HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be HH:MM") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValidationError(f"{field_name} must be HH:MM")
    return time(hour, minute)


def optional_hhmm(raw: Any, *, field_name: str) -> time | None:
    if raw is None or raw == "":
        return None
    return parse_hhmm(raw, field_name=field_name)


def format_hhmm(value: time | None) -> str | None:
    if value is None:
        return None
    return f"{value.hour:02d}:{value.minute:02d}"


def parse_notification_settings(settings: dict[str, Any] | None) -> NotificationSettings:
    blob = settings.get("notifications") if isinstance(settings, dict) else None
    if not isinstance(blob, dict):
        blob = {}
    window_start = (
        parse_hhmm(blob["window_start"], field_name="window_start")
        if "window_start" in blob and blob["window_start"] not in (None, "")
        else DEFAULT_WINDOW_START
    )
    window_end = (
        parse_hhmm(blob["window_end"], field_name="window_end")
        if "window_end" in blob and blob["window_end"] not in (None, "")
        else DEFAULT_WINDOW_END
    )
    if window_start >= window_end:
        raise ValidationError("notification window_start must be before window_end")
    quiet_start = optional_hhmm(
        blob.get("quiet_hours_start"),
        field_name="quiet_hours_start",
    )
    quiet_end = optional_hhmm(
        blob.get("quiet_hours_end"),
        field_name="quiet_hours_end",
    )
    if (quiet_start is None) != (quiet_end is None):
        raise ValidationError("quiet hours require both start and end")
    return NotificationSettings(
        window_start=window_start,
        window_end=window_end,
        quiet_hours_start=quiet_start,
        quiet_hours_end=quiet_end,
    )


def notification_settings_payload(parsed: NotificationSettings) -> dict[str, str | None]:
    return {
        "window_start": format_hhmm(parsed.window_start),
        "window_end": format_hhmm(parsed.window_end),
        "quiet_hours_start": format_hhmm(parsed.quiet_hours_start),
        "quiet_hours_end": format_hhmm(parsed.quiet_hours_end),
    }


def merge_company_settings(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Replace settings, validating notifications if present."""
    merged = dict(incoming)
    if "notifications" in merged:
        parsed = parse_notification_settings(merged)
        merged["notifications"] = notification_settings_payload(parsed)
    elif isinstance(existing, dict) and "notifications" in existing:
        parse_notification_settings(existing)
    return merged
