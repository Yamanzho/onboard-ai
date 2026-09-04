"""Assignment-time course snapshot helpers."""

from __future__ import annotations

from uuid import uuid4

from app.db.models.step import Step
from app.services.course_snapshot import (
    build_structure_snapshot,
    resolve_progress_step_fields,
    snapshot_step_map,
)


def test_snapshot_preserves_order_and_content_copy() -> None:
    program_id = uuid4()
    company_id = uuid4()
    first = Step(
        id=uuid4(),
        company_id=company_id,
        program_id=program_id,
        title="A",
        step_type="content",
        position=1,
        content={"body": "second-in-id"},
        is_required=True,
    )
    second = Step(
        id=uuid4(),
        company_id=company_id,
        program_id=program_id,
        title="B",
        step_type="content",
        position=0,
        content={"body": "first"},
        is_required=False,
    )
    snapshot = build_structure_snapshot(3, [first, second])
    assert snapshot["revision"] == 3
    assert [item["title"] for item in snapshot["steps"]] == ["B", "A"]
    snapshot["steps"][0]["content"]["body"] = "mutated"
    assert second.content["body"] == "first"


def test_resolve_prefers_snapshot_over_live_step() -> None:
    step_id = uuid4()
    live = Step(
        id=step_id,
        company_id=uuid4(),
        program_id=uuid4(),
        title="Live title",
        step_type="content",
        position=0,
        content={"body": "live"},
        is_required=True,
    )
    snapshot = {
        "revision": 1,
        "steps": [
            {
                "id": str(step_id),
                "title": "Assigned title",
                "description": None,
                "step_type": "content",
                "position": 0,
                "is_required": True,
                "estimated_minutes": None,
                "content": {"body": "assigned"},
            }
        ],
    }
    fields = resolve_progress_step_fields(
        step_id,
        live_step=live,
        snapshot=snapshot,
    )
    assert fields is not None
    assert fields["title"] == "Assigned title"
    assert fields["content"]["body"] == "assigned"
    assert snapshot_step_map(None) == {}
    fallback = resolve_progress_step_fields(
        step_id,
        live_step=live,
        snapshot=None,
    )
    assert fallback is not None
    assert fallback["content"]["body"] == "live"
