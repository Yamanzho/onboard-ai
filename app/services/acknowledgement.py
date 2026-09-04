from __future__ import annotations

from collections.abc import Sequence

from app.db.models.assignment_acknowledgement_item import AssignmentAcknowledgementItem
from app.schemas.assignment import AcknowledgementItemResponse, AcknowledgementSummary


def acknowledgement_summary(
    items: Sequence[AssignmentAcknowledgementItem],
) -> AcknowledgementSummary:
    required = [item for item in items if item.is_required]
    acknowledged_required = [item for item in required if item.acknowledged_at is not None]
    first = next(iter(items), None)
    version = getattr(first, "article_version", None) if first is not None else None
    title = version.title if version is not None else None
    total_required = len(required)
    done = len(acknowledged_required)
    completed = total_required == 0 or done == total_required
    percentage = 100.0 if completed else (done / total_required * 100.0 if total_required else 0.0)
    return AcknowledgementSummary(
        total_documents=len(items),
        required_documents=total_required,
        acknowledged_required_count=done,
        completed=completed,
        title=title,
        percentage=round(percentage, 2),
    )


def acknowledgement_item_response(
    item: AssignmentAcknowledgementItem,
) -> AcknowledgementItemResponse:
    version = item.article_version
    return AcknowledgementItemResponse(
        id=item.id,
        assignment_id=item.assignment_id,
        article_id=item.article_id,
        article_version_id=item.article_version_id,
        position=item.position,
        is_required=item.is_required,
        acknowledged_at=item.acknowledged_at,
        title=version.title if version is not None else "",
        version=version.version if version is not None else 0,
        body_format=version.body_format if version is not None else "markdown",
    )


def next_incomplete_required(
    items: Sequence[AssignmentAcknowledgementItem],
) -> AssignmentAcknowledgementItem | None:
    for item in items:
        if item.is_required and item.acknowledged_at is None:
            return item
    return None
