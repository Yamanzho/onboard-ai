"""Assignment-time course structure snapshot.

OnboardingProgram.revision identifies a generation. Live Step rows are
mutated in place after a run ends, so historical progress must not read
current Step.content as if it belonged to an older revision.

Each Assignment stores a JSON snapshot of the ordered steps at create time.
While the assignment is active the course is locked, so the snapshot is the
content the employee actually ran. Later edits bump revision but leave the
snapshot untouched.

Legacy assignments with a null snapshot fall back to live steps
(identity-only; content is not historically guaranteed).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from app.db.models.step import Step


def build_structure_snapshot(revision: int, steps: list[Step]) -> dict[str, Any]:
    ordered = sorted(steps, key=lambda step: step.position)
    return {
        "revision": revision,
        "steps": [
            {
                "id": str(step.id),
                "title": step.title,
                "description": step.description,
                "step_type": step.step_type,
                "position": step.position,
                "is_required": step.is_required,
                "estimated_minutes": step.estimated_minutes,
                "content": deepcopy(step.content) if isinstance(step.content, dict) else {},
            }
            for step in ordered
        ],
    }


def snapshot_step_map(snapshot: dict[str, Any] | None) -> dict[UUID, dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return {}
    raw = snapshot.get("steps")
    if not isinstance(raw, list):
        return {}
    mapped: dict[UUID, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if raw_id is None:
            continue
        try:
            mapped[UUID(str(raw_id))] = item
        except ValueError:
            continue
    return mapped


def resolve_progress_step_fields(
    step_id: UUID,
    *,
    live_step: Step | None,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Prefer the assignment snapshot so later course edits cannot rewrite history."""
    snapped = snapshot_step_map(snapshot).get(step_id)
    if snapped is not None:
        content = snapped.get("content")
        return {
            "title": str(snapped.get("title") or ""),
            "description": snapped.get("description"),
            "step_type": str(snapped.get("step_type") or "content"),
            "content": dict(content) if isinstance(content, dict) else {},
            "position": int(snapped.get("position") or 0),
        }
    if live_step is None:
        return None
    return {
        "title": live_step.title,
        "description": live_step.description,
        "step_type": live_step.step_type,
        "content": dict(live_step.content) if isinstance(live_step.content, dict) else {},
        "position": live_step.position,
    }


def order_records_by_snapshot(records: list[Any], snapshot: dict[str, Any] | None) -> list[Any]:
    """Sort progress rows by assignment snapshot position when a snapshot exists."""
    mapped = snapshot_step_map(snapshot)
    if not mapped:
        return list(records)

    def _key(record: Any) -> tuple[int, int, str]:
        step_id = getattr(record, "step_id", None)
        snapped = mapped.get(step_id) if step_id is not None else None
        if snapped is None:
            return (1, 0, str(step_id or ""))
        return (0, int(snapped.get("position") or 0), str(step_id))

    return sorted(records, key=_key)
