"""Assignment reminder enqueue, employee preference, and periodic scan."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import (
    AssignmentStatus,
    CompanyAuditAction,
    ReminderMode,
)
from app.db.models.assignment import Assignment
from app.db.models.assignment_reminder_preference import AssignmentReminderPreference
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.company_audit import record_company_audit
from app.services.notification_settings import parse_notification_settings
from app.services.reminder_messages import (
    format_initial_assignment_message,
    format_reminder_message,
)
from app.services.reminder_policy import (
    MANUAL_REMIND_COOLDOWN,
    company_local,
    decide_automated_slot,
    initial_source_key,
    is_assignment_outbound_type,
    manual_cooldown_active,
    manual_remind_blocked,
    manual_source_key,
    parse_assignment_id_from_source_key,
    reminder_source_key,
)
from app.services.telegram_outbound import TelegramOutboundService
from app.services.tenancy import ensure_same_company

logger = logging.getLogger("app.reminders")

_OPEN_STATUSES = frozenset(
    {
        AssignmentStatus.PENDING.value,
        AssignmentStatus.IN_PROGRESS.value,
    }
)
_SCAN_LIMIT = 500


class ReminderService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        outbound: TelegramOutboundService | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._outbound = outbound or TelegramOutboundService()

    async def scan_due(self, *, now: datetime | None = None) -> dict[str, int]:
        clock = now or datetime.now(UTC)
        scanned = 0
        enqueued = 0
        async with self._uow_factory() as uow:
            await uow.enter_platform()
            assignments = await uow.assignments.list_open_for_reminders(limit=_SCAN_LIMIT)
            assignment_ids = [row.id for row in assignments]
            await uow.commit()
        for assignment_id in assignment_ids:
            scanned += 1
            async with self._uow_factory() as uow:
                await uow.enter_platform()
                assignment = await uow.assignments.get_by_id(assignment_id)
                created = False
                try:
                    if assignment is not None:
                        created = await self._maybe_enqueue_automated(
                            uow, assignment, clock
                        )
                    await uow.commit()
                except Exception:
                    await uow.rollback()
                    logger.exception(
                        "assignment_reminder_scan assignment_id=%s failed",
                        assignment_id,
                    )
                    created = False
            if created:
                enqueued += 1
        return {"scanned": scanned, "enqueued": enqueued}

    async def assignment_still_deliverable(
        self,
        *,
        source_type: str,
        source_key: str,
    ) -> bool:
        if not is_assignment_outbound_type(source_type):
            return True
        assignment_id = parse_assignment_id_from_source_key(source_key)
        if assignment_id is None:
            return False
        async with self._uow_factory() as uow:
            await uow.enter_platform()
            assignment = await uow.assignments.get_by_id(assignment_id)
            await uow.commit()
        if assignment is None:
            return False
        return assignment.status in _OPEN_STATUSES

    async def remind_now(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID,
        now: datetime | None = None,
    ) -> dict:
        clock = now or datetime.now(UTC)
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment, employee, company, program_title = await self._load_open(
                uow, assignment_id, company_id
            )
            preference = await self._ensure_preference(uow, assignment)
            if manual_remind_blocked(preference.mode):
                raise ConflictError("Employee disabled reminders for this assignment.")
            if manual_cooldown_active(
                now=clock,
                last_manual_at=preference.last_manual_reminder_at,
            ):
                raise ConflictError("Remind now is on cooldown")
            if employee.telegram_chat_id is None:
                raise ValidationError("Employee has no linked Telegram chat")
            event_id = uuid4()
            body = format_reminder_message(
                program_title=program_title,
                priority=assignment.priority,
                due_at=assignment.due_at,
                timezone_name=company.timezone,
                overdue=assignment.overdue,
                assignment_type=assignment.assignment_type,
            )
            existing = await uow.telegram_outbound.get_by_source(
                source_type="assignment_manual_reminder",
                source_key=manual_source_key(assignment.id, event_id),
            )
            row = await self._outbound.enqueue_in_uow(
                uow,
                company_id=company.id,
                employee_id=employee.id,
                chat_id=employee.telegram_chat_id,
                source_type="assignment_manual_reminder",
                source_key=manual_source_key(assignment.id, event_id),
                body=body,
            )
            inserted = existing is None
            if inserted:
                await uow.assignment_reminders.update(
                    preference.id,
                    last_manual_reminder_at=clock,
                )
            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=actor_employee_id,
                action=CompanyAuditAction.ASSIGNMENT_REMINDED.value,
                resource_type="assignment",
                resource_id=assignment.id,
                summary="Sent a manual assignment reminder",
                details={"source_type": "assignment_manual_reminder"},
            )
            await uow.commit()
            return {
                "enqueued": inserted,
                "outbound_id": row.id,
                "status": row.status,
                "cooldown_seconds": int(MANUAL_REMIND_COOLDOWN.total_seconds()),
            }

    async def acknowledge(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
        employee_id: UUID,
        now: datetime | None = None,
    ) -> AssignmentReminderPreference:
        return await self._update_preference(
            assignment_id,
            company_id=company_id,
            employee_id=employee_id,
            now=now,
            acknowledge=True,
        )

    async def reduce(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
        employee_id: UUID,
        now: datetime | None = None,
    ) -> AssignmentReminderPreference:
        return await self._update_preference(
            assignment_id,
            company_id=company_id,
            employee_id=employee_id,
            now=now,
            mode=ReminderMode.REDUCED.value,
        )

    async def disable(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
        employee_id: UUID,
        now: datetime | None = None,
    ) -> AssignmentReminderPreference:
        return await self._update_preference(
            assignment_id,
            company_id=company_id,
            employee_id=employee_id,
            now=now,
            mode=ReminderMode.DISABLED.value,
        )

    async def get_assignment_notifications(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
    ) -> dict:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment, _employee, _company, program_title = await self._load_assignment(
                uow, assignment_id, company_id
            )
            preference = await uow.assignment_reminders.get_by_assignment_id(assignment_id)
            rows = await uow.telegram_outbound.list_for_assignment(assignment_id)
            await uow.commit()
        return {
            "assignment_id": assignment.id,
            "program_title": program_title,
            "preference": preference,
            "items": rows,
        }

    async def enqueue_initial_in_uow(
        self,
        uow: UnitOfWork,
        *,
        assignment: Assignment,
        employee: Employee,
        company: Company,
        program_title: str,
        now: datetime,
    ) -> None:
        await self._ensure_preference(uow, assignment)
        if employee.telegram_chat_id is None:
            return
        body = format_initial_assignment_message(
            program_title=program_title,
            priority=assignment.priority,
            due_at=assignment.due_at,
            timezone_name=company.timezone,
            overdue=assignment.overdue,
            assignment_type=assignment.assignment_type,
        )
        await self._outbound.enqueue_in_uow(
            uow,
            company_id=company.id,
            employee_id=employee.id,
            chat_id=employee.telegram_chat_id,
            source_type="assignment_initial",
            source_key=initial_source_key(assignment.id),
            body=body,
        )

    async def _maybe_enqueue_automated(
        self,
        uow: UnitOfWork,
        assignment: Assignment,
        now: datetime,
    ) -> bool:
        refreshed = await uow.assignments.get_by_id(assignment.id)
        if refreshed is None or refreshed.status not in _OPEN_STATUSES:
            return False
        employee = await uow.employees.get_by_id(refreshed.employee_id)
        company = await uow.companies.get_by_id(refreshed.company_id)
        if employee is None or company is None or employee.telegram_chat_id is None:
            return False
        program_title = await self._display_title(uow, refreshed)
        preference = await self._ensure_preference(uow, refreshed)
        try:
            settings = parse_notification_settings(company.settings)
        except ValidationError:
            logger.warning(
                "assignment_reminder_scan company_id=%s invalid notification settings",
                company.id,
            )
            return False
        local_today = company_local(now, company.timezone).date()
        sent_slots: set[int] = set()
        for slot in (1, 2):
            existing = await uow.telegram_outbound.get_by_source(
                source_type="assignment_reminder",
                source_key=reminder_source_key(refreshed.id, local_today, slot),
            )
            if existing is not None:
                sent_slots.add(slot)
        decision = decide_automated_slot(
            now=now,
            timezone_name=company.timezone,
            settings=settings,
            assignment_status=refreshed.status,
            priority=refreshed.priority,
            mode=preference.mode,
            acknowledged_until_date=preference.acknowledged_until_date,
            last_automated_at=preference.last_automated_reminder_at,
            sent_slots_today=sent_slots,
        )
        if not decision.eligible or decision.slot is None:
            return False
        before = await uow.telegram_outbound.get_by_source(
            source_type="assignment_reminder",
            source_key=reminder_source_key(refreshed.id, local_today, decision.slot),
        )
        if before is not None:
            return False
        body = format_reminder_message(
            program_title=program_title,
            priority=refreshed.priority,
            due_at=refreshed.due_at,
            timezone_name=company.timezone,
            overdue=refreshed.overdue,
            assignment_type=refreshed.assignment_type,
        )
        await self._outbound.enqueue_in_uow(
            uow,
            company_id=company.id,
            employee_id=employee.id,
            chat_id=employee.telegram_chat_id,
            source_type="assignment_reminder",
            source_key=reminder_source_key(refreshed.id, local_today, decision.slot),
            body=body,
        )
        await uow.assignment_reminders.update(
            preference.id,
            last_automated_reminder_at=now,
        )
        return True

    async def _update_preference(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
        employee_id: UUID,
        now: datetime | None,
        mode: str | None = None,
        acknowledge: bool = False,
    ) -> AssignmentReminderPreference:
        clock = now or datetime.now(UTC)
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment, _employee, company, _title = await self._load_assignment(
                uow, assignment_id, company_id
            )
            if assignment.employee_id != employee_id:
                raise NotFoundError(f"Assignment {assignment_id} not found")
            if assignment.status == AssignmentStatus.CANCELLED.value:
                raise ValidationError("Cannot update reminders on a cancelled assignment")
            preference = await self._ensure_preference(uow, assignment)
            values: dict = {"updated_by_employee_at": clock}
            if mode is not None:
                values["mode"] = mode
            if acknowledge:
                local_today = company_local(clock, company.timezone).date()
                values["acknowledged_until_date"] = local_today
                values["last_acknowledged_at"] = clock
            updated = await uow.assignment_reminders.update(preference.id, **values)
            assert updated is not None
            await uow.commit()
            return updated

    async def _ensure_preference(
        self,
        uow: UnitOfWork,
        assignment: Assignment,
    ) -> AssignmentReminderPreference:
        existing = await uow.assignment_reminders.get_by_assignment_id(assignment.id)
        if existing is not None:
            return existing
        return await uow.assignment_reminders.create(
            AssignmentReminderPreference(
                company_id=assignment.company_id,
                assignment_id=assignment.id,
                employee_id=assignment.employee_id,
                mode=ReminderMode.DEFAULT.value,
            )
        )

    async def _load_open(
        self,
        uow: UnitOfWork,
        assignment_id: UUID,
        company_id: UUID,
    ) -> tuple[Assignment, Employee, Company, str]:
        assignment, employee, company, title = await self._load_assignment(
            uow, assignment_id, company_id
        )
        if assignment.status == AssignmentStatus.CANCELLED.value:
            raise ValidationError("Cannot remind a cancelled assignment")
        if assignment.status == AssignmentStatus.COMPLETED.value:
            raise ValidationError("Assignment is already completed")
        if assignment.status not in _OPEN_STATUSES:
            raise ValidationError("Assignment is not active")
        return assignment, employee, company, title

    async def _load_assignment(
        self,
        uow: UnitOfWork,
        assignment_id: UUID,
        company_id: UUID,
    ) -> tuple[Assignment, Employee, Company, str]:
        assignment = await uow.assignments.get_by_id(assignment_id)
        if assignment is None:
            raise NotFoundError(f"Assignment {assignment_id} not found")
        ensure_same_company(
            resource_company_id=assignment.company_id,
            actor_company_id=company_id,
            not_found_message=f"Assignment {assignment_id} not found",
        )
        employee = await uow.employees.get_by_id(assignment.employee_id)
        company = await uow.companies.get_by_id(assignment.company_id)
        if employee is None or company is None:
            raise NotFoundError(f"Assignment {assignment_id} not found")
        title = await self._display_title(uow, assignment)
        return assignment, employee, company, title

    async def _display_title(self, uow: UnitOfWork, assignment: Assignment) -> str:
        if assignment.program_id is not None:
            program = await uow.onboarding_programs.get_by_id(assignment.program_id)
            return program.title if program is not None else "курс"
        items = await uow.assignment_acknowledgement_items.list_by_assignment_id(
            assignment.id
        )
        if items and items[0].article_version is not None:
            return items[0].article_version.title
        return "документы"
