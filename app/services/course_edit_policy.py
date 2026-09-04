"""Course structure-edit policy.

OnboardingProgram is the Course aggregate. Step is an inline Training/module.
There is no standalone Training table.

Lock:
    pending / in_progress assignments lock structure and training content.
    completed / cancelled do not. program.is_active is not the lock.

Revision (deterministic):
    Starts at 1. Increments once per successful structure/content mutation
    in the same transaction (create/delete/reorder steps; update of
    step_type, is_required, or content). A multi-step reorder is one bump.
    No-op reorder does not bump. Failed mutations do not bump.

    Does not increment for course title/description, publish/archive, or
    step title/description/estimated_minutes only.

Historical content:
    Assignment.structure_snapshot freezes ordered step content at assign time.
    program_revision is the generation id; the snapshot is the content that
    generation actually contained. Live Step rows may change after a run ends.
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ConflictError
from app.db.uow import UnitOfWork

COURSE_LOCKED_MESSAGE = (
    "Course cannot be changed while employees have active assignments."
)

# Step fields that change learning structure/content (lock + revision).
STRUCTURE_STEP_FIELDS = frozenset({"step_type", "is_required", "content"})


async def has_active_assignments(uow: UnitOfWork, program_id: UUID) -> bool:
    return await uow.assignments.has_active_for_program(program_id)


async def assert_program_structure_editable(
    uow: UnitOfWork,
    program_id: UUID,
) -> None:
    if await has_active_assignments(uow, program_id):
        raise ConflictError(COURSE_LOCKED_MESSAGE)


async def bump_program_revision(uow: UnitOfWork, program_id: UUID) -> int:
    """Increment revision after a successful structure/content mutation."""
    program = await uow.onboarding_programs.get_by_id(program_id)
    assert program is not None
    next_revision = program.revision + 1
    updated = await uow.onboarding_programs.update(program_id, revision=next_revision)
    assert updated is not None
    return next_revision


def step_update_touches_structure(values: dict) -> bool:
    return bool(STRUCTURE_STEP_FIELDS.intersection(values))
