"""Deterministic assistant orchestration. AIChatService stays the RAG path."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.exceptions import NotFoundError
from app.db.assignment_rules import assignment_sort_key
from app.db.enums import (
    AssignmentStatus,
    AssignmentType,
    AssistantIntent,
    EmployeeStatus,
)
from app.db.models.assignment import Assignment
from app.db.uow import UnitOfWork
from app.services.ai.chat import AIChatService, ChatAnswer
from app.services.ai.context import Citation
from app.services.ai.llm import LLMProvider
from app.services.assignment import AssignmentService
from app.services.assistant.intent_router import IntentRouter, RoutedIntent
from app.services.assistant.messages import (
    CONTINUE_MANY,
    CONTINUE_NONE,
    CONTINUE_ONE,
    GREETING_TEXT,
    HELP_TEXT,
    NO_ACTIVE_ASSIGNMENTS,
    NO_ANSWER_NO_OWNER,
    NO_TRAINING_CONTEXT,
    RESPONSIBILITY_UNCONFIGURED,
    RESPONSIBILITY_UNKNOWN_TOPIC,
    THANKS_TEXT,
    UNKNOWN_TEXT,
    company_timezone,
    format_assignment_line,
    format_assignment_list,
    format_responsibility,
    format_training_help,
    format_unconfigured_with_manager,
)
from app.services.assistant.topic_matcher import TopicMatcher
from app.services.course_snapshot import resolve_progress_step_fields
from app.services.learning_progress import resolve_resume_item
from app.services.onboarding_program import OnboardingProgramService
from app.services.progress import ProgressService
from app.services.question_topic import QuestionTopicService
from app.services.responsibility import ResponsibilityLookupService, ResponsibilityResult
from app.services.step_content import normalize_step_content

logger = logging.getLogger("app.assistant")

_OPEN_STATUSES = frozenset(
    {
        AssignmentStatus.PENDING.value,
        AssignmentStatus.IN_PROGRESS.value,
    }
)
ACTION_NONE = "none"
ACTION_OPEN = "open_assignment"
ACTION_CHOOSE = "choose_assignment"
ACTION_RESUME = "resume_learning"


@dataclass(frozen=True, slots=True)
class AssistantAssignmentRef:
    id: UUID
    title: str
    assignment_type: str


@dataclass(frozen=True, slots=True)
class AssistantResult:
    kind: str
    text: str
    intent: str
    action: str = ACTION_NONE
    assignment_ids: tuple[UUID, ...] = ()
    assignments: tuple[AssistantAssignmentRef, ...] = ()
    conversation_id: UUID | None = None
    citations: tuple[Citation, ...] = ()
    no_answer: bool = False
    used_retriever: bool = False
    used_llm: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class AssistantOrchestrator:
    """Route → existing services → grounded response. No agent loop."""

    def __init__(
        self,
        *,
        chat_service: AIChatService | None = None,
        assignment_service: AssignmentService | None = None,
        progress_service: ProgressService | None = None,
        program_service: OnboardingProgramService | None = None,
        topic_service: QuestionTopicService | None = None,
        responsibility: ResponsibilityLookupService | None = None,
        intent_router: IntentRouter | None = None,
        topic_matcher: TopicMatcher | None = None,
        llm_provider: LLMProvider | None = None,
        uow_factory: Callable[[], UnitOfWork] | None = None,
    ) -> None:
        self._chat = chat_service or AIChatService()
        self._assignments = assignment_service or AssignmentService()
        self._progress = progress_service or ProgressService()
        self._programs = program_service or OnboardingProgramService()
        self._topics = topic_service or QuestionTopicService()
        self._responsibility = responsibility or ResponsibilityLookupService()
        self._llm = llm_provider
        self._router = intent_router or IntentRouter(llm_provider=self._llm)
        self._topic_matcher = topic_matcher or TopicMatcher(llm_provider=self._llm)
        self._uow_factory = uow_factory or UnitOfWork

    async def handle(
        self,
        message: str,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        conversation_id: UUID | None = None,
        idempotency_key: str | None = None,
        telegram_delivery: bool = False,
        on_expensive_call: Callable[[], None] | None = None,
    ) -> AssistantResult:
        routed = await self._router.route(message)
        intent = routed.intent
        if intent is AssistantIntent.GREETING:
            return _text_result(intent, GREETING_TEXT, used_llm=routed.used_llm)
        if intent is AssistantIntent.THANKS:
            return _text_result(intent, THANKS_TEXT, used_llm=routed.used_llm)
        if intent is AssistantIntent.HELP:
            return _text_result(intent, HELP_TEXT, used_llm=routed.used_llm)
        if intent is AssistantIntent.NEXT_TASK:
            return await self._next_task(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                used_llm=routed.used_llm,
            )
        if intent is AssistantIntent.ASSIGNMENT_STATUS:
            return await self._assignment_status(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                used_llm=routed.used_llm,
            )
        if intent is AssistantIntent.CONTINUE_LEARNING:
            return await self._continue_learning(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                used_llm=routed.used_llm,
            )
        if intent is AssistantIntent.TRAINING_HELP:
            return await self._training_help(
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                used_llm=routed.used_llm,
            )
        if intent is AssistantIntent.RESPONSIBLE_TOPIC:
            return await self._responsible_topic(
                message,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                topic_hint=routed.topic_hint,
                used_llm=routed.used_llm,
            )
        if intent is AssistantIntent.COMPANY_KNOWLEDGE:
            return await self._company_knowledge(
                message,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                conversation_id=conversation_id,
                idempotency_key=idempotency_key,
                telegram_delivery=telegram_delivery,
                on_expensive_call=on_expensive_call,
                routed=routed,
            )
        return await self._unknown(
            message,
            actor_company_id=actor_company_id,
            actor_employee_id=actor_employee_id,
            actor_role=actor_role,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            telegram_delivery=telegram_delivery,
            on_expensive_call=on_expensive_call,
            routed=routed,
        )

    async def _next_task(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        used_llm: bool,
    ) -> AssistantResult:
        views = await self._active_views(
            actor_company_id=actor_company_id,
            actor_employee_id=actor_employee_id,
            actor_role=actor_role,
        )
        if not views:
            return _text_result(
                AssistantIntent.NEXT_TASK,
                NO_ACTIVE_ASSIGNMENTS,
                used_llm=used_llm,
            )
        lines = [
            format_assignment_line(
                index=index,
                title=view["title"],
                priority=view["assignment"].priority,
                due_at=view["assignment"].due_at,
                status=view["assignment"].status,
                progress_label=view["progress_label"],
                timezone_name=view["timezone"],
            )
            for index, view in enumerate(views, start=1)
        ]
        refs = tuple(
            AssistantAssignmentRef(
                id=view["assignment"].id,
                title=view["title"],
                assignment_type=view["assignment"].assignment_type,
            )
            for view in views
        )
        return AssistantResult(
            kind=AssistantIntent.NEXT_TASK.value,
            text=format_assignment_list(lines),
            intent=AssistantIntent.NEXT_TASK.value,
            assignment_ids=tuple(ref.id for ref in refs),
            assignments=refs,
            used_llm=used_llm,
        )

    async def _assignment_status(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        used_llm: bool,
    ) -> AssistantResult:
        views = await self._active_views(
            actor_company_id=actor_company_id,
            actor_employee_id=actor_employee_id,
            actor_role=actor_role,
        )
        if not views:
            return _text_result(
                AssistantIntent.ASSIGNMENT_STATUS,
                NO_ACTIVE_ASSIGNMENTS,
                used_llm=used_llm,
            )
        if len(views) == 1:
            view = views[0]
            line = format_assignment_line(
                index=1,
                title=view["title"],
                priority=view["assignment"].priority,
                due_at=view["assignment"].due_at,
                status=view["assignment"].status,
                progress_label=view["progress_label"],
                timezone_name=view["timezone"],
            )
            text = f"Текущий статус:\n{line}"
        else:
            lines = [
                format_assignment_line(
                    index=index,
                    title=view["title"],
                    priority=view["assignment"].priority,
                    due_at=view["assignment"].due_at,
                    status=view["assignment"].status,
                    progress_label=view["progress_label"],
                    timezone_name=view["timezone"],
                )
                for index, view in enumerate(views[:5], start=1)
            ]
            text = format_assignment_list(
                lines,
                heading="Краткий статус активных заданий:",
            )
        refs = tuple(
            AssistantAssignmentRef(
                id=view["assignment"].id,
                title=view["title"],
                assignment_type=view["assignment"].assignment_type,
            )
            for view in views
        )
        return AssistantResult(
            kind=AssistantIntent.ASSIGNMENT_STATUS.value,
            text=text,
            intent=AssistantIntent.ASSIGNMENT_STATUS.value,
            assignment_ids=tuple(ref.id for ref in refs),
            assignments=refs,
            used_llm=used_llm,
        )

    async def _continue_learning(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        used_llm: bool,
    ) -> AssistantResult:
        views = await self._active_views(
            actor_company_id=actor_company_id,
            actor_employee_id=actor_employee_id,
            actor_role=actor_role,
        )
        courses = [
            view
            for view in views
            if view["assignment"].assignment_type == AssignmentType.PROGRAM.value
        ]
        if not courses:
            return _text_result(
                AssistantIntent.CONTINUE_LEARNING,
                CONTINUE_NONE if views else NO_ACTIVE_ASSIGNMENTS,
                used_llm=used_llm,
            )
        refs = tuple(
            AssistantAssignmentRef(
                id=view["assignment"].id,
                title=view["title"],
                assignment_type=view["assignment"].assignment_type,
            )
            for view in courses
        )
        if len(courses) == 1:
            return AssistantResult(
                kind=AssistantIntent.CONTINUE_LEARNING.value,
                text=CONTINUE_ONE,
                intent=AssistantIntent.CONTINUE_LEARNING.value,
                action=ACTION_RESUME,
                assignment_ids=(refs[0].id,),
                assignments=refs,
                used_llm=used_llm,
            )
        return AssistantResult(
            kind=AssistantIntent.CONTINUE_LEARNING.value,
            text=CONTINUE_MANY,
            intent=AssistantIntent.CONTINUE_LEARNING.value,
            action=ACTION_CHOOSE,
            assignment_ids=tuple(ref.id for ref in refs),
            assignments=refs,
            used_llm=used_llm,
        )

    async def _training_help(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        used_llm: bool,
    ) -> AssistantResult:
        views = await self._active_views(
            actor_company_id=actor_company_id,
            actor_employee_id=actor_employee_id,
            actor_role=actor_role,
        )
        courses = [
            view
            for view in views
            if view["assignment"].assignment_type == AssignmentType.PROGRAM.value
        ]
        if not courses:
            return _text_result(
                AssistantIntent.TRAINING_HELP,
                NO_TRAINING_CONTEXT,
                used_llm=used_llm,
            )
        view = courses[0]
        assignment = view["assignment"]
        items = await self._progress.get_progress(
            assignment.id, company_id=actor_company_id
        )
        current = resolve_resume_item(items)
        if current is None:
            return _text_result(
                AssistantIntent.TRAINING_HELP,
                NO_TRAINING_CONTEXT,
                used_llm=used_llm,
            )
        live_steps = await self._progress.get_steps_for_progress_items(
            items, company_id=actor_company_id
        )
        fields = resolve_progress_step_fields(
            current.step_id,
            live_step=live_steps.get(current.step_id),
            snapshot=assignment.structure_snapshot,
        )
        if fields is None:
            return _text_result(
                AssistantIntent.TRAINING_HELP,
                NO_TRAINING_CONTEXT,
                used_llm=used_llm,
            )
        excerpt = _step_excerpt(fields)
        explanation = excerpt or "В назначенном шаге нет текстового материала."
        return AssistantResult(
            kind=AssistantIntent.TRAINING_HELP.value,
            text=format_training_help(
                program_title=view["title"],
                step_title=str(fields.get("title") or "Шаг"),
                explanation=explanation,
            ),
            intent=AssistantIntent.TRAINING_HELP.value,
            assignment_ids=(assignment.id,),
            assignments=(
                AssistantAssignmentRef(
                    id=assignment.id,
                    title=view["title"],
                    assignment_type=assignment.assignment_type,
                ),
            ),
            used_llm=used_llm,
            metadata={"step_title": fields.get("title")},
        )

    async def _responsible_topic(
        self,
        message: str,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        topic_hint: str | None,
        used_llm: bool,
    ) -> AssistantResult:
        topics = await self._topics.list_topics(
            actor_company_id,
            actor_company_id=actor_company_id,
            is_active=True,
        )
        match = await self._topic_matcher.match(
            message, topics, topic_hint=topic_hint
        )
        if match is None:
            return _text_result(
                AssistantIntent.RESPONSIBLE_TOPIC,
                RESPONSIBILITY_UNKNOWN_TOPIC,
                used_llm=used_llm,
            )
        mapped = await self._responsibility.lookup(
            actor_company_id, topic_id=match.topic_id
        )
        if mapped is None:
            manager = await self._manager_fallback(
                actor_company_id, actor_employee_id
            )
            text = (
                format_unconfigured_with_manager(manager[0], manager[1])
                if manager
                else RESPONSIBILITY_UNCONFIGURED
            )
            return _text_result(
                AssistantIntent.RESPONSIBLE_TOPIC,
                text,
                used_llm=used_llm or match.used_llm,
                metadata={"topic_slug": match.slug, "configured": False},
            )
        return AssistantResult(
            kind=AssistantIntent.RESPONSIBLE_TOPIC.value,
            text=_responsibility_text(mapped),
            intent=AssistantIntent.RESPONSIBLE_TOPIC.value,
            used_llm=used_llm or match.used_llm,
            metadata={"topic_slug": match.slug, "configured": True},
        )

    async def _company_knowledge(
        self,
        message: str,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        conversation_id: UUID | None,
        idempotency_key: str | None,
        telegram_delivery: bool,
        on_expensive_call: Callable[[], None] | None,
        routed: RoutedIntent,
    ) -> AssistantResult:
        if on_expensive_call is not None:
            on_expensive_call()
        answer = await self._chat.answer(
            message,
            actor_company_id=actor_company_id,
            actor_employee_id=actor_employee_id,
            actor_role=actor_role,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            telegram_delivery=telegram_delivery,
        )
        if answer.no_answer:
            fallback = await self._responsible_topic(
                message,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                topic_hint=routed.topic_hint,
                used_llm=True,
            )
            if fallback.metadata.get("configured"):
                return AssistantResult(
                    kind="no_answer_responsibility",
                    text=fallback.text,
                    intent=AssistantIntent.COMPANY_KNOWLEDGE.value,
                    conversation_id=answer.conversation_id,
                    no_answer=True,
                    used_retriever=True,
                    used_llm=True,
                    metadata=fallback.metadata,
                )
            return AssistantResult(
                kind="no_answer",
                text=NO_ANSWER_NO_OWNER,
                intent=AssistantIntent.COMPANY_KNOWLEDGE.value,
                conversation_id=answer.conversation_id,
                no_answer=True,
                used_retriever=True,
                used_llm=True,
            )
        return _from_chat(answer, routed.intent, used_retriever=True)

    async def _unknown(
        self,
        message: str,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
        conversation_id: UUID | None,
        idempotency_key: str | None,
        telegram_delivery: bool,
        on_expensive_call: Callable[[], None] | None,
        routed: RoutedIntent,
    ) -> AssistantResult:
        from app.services.assistant.intent_router import looks_knowledge_like

        if looks_knowledge_like(message):
            return await self._company_knowledge(
                message,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
                conversation_id=conversation_id,
                idempotency_key=idempotency_key,
                telegram_delivery=telegram_delivery,
                on_expensive_call=on_expensive_call,
                routed=routed,
            )
        return _text_result(
            AssistantIntent.UNKNOWN, UNKNOWN_TEXT, used_llm=routed.used_llm
        )

    async def _active_views(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
    ) -> list[dict[str, Any]]:
        rows = await self._assignments.get_employee_assignments(
            actor_employee_id,
            company_id=actor_company_id,
            limit=100,
        )
        active = [row for row in rows if row.status in _OPEN_STATUSES]
        active.sort(
            key=lambda row: assignment_sort_key(
                priority=row.priority,
                due_at=row.due_at,
                status=row.status,
                assigned_at=row.assigned_at,
            )
        )
        summaries = await self._assignments.acknowledgement_summaries(
            active, company_id=actor_company_id
        )
        timezone = await self._employee_timezone(
            actor_company_id, actor_employee_id
        )
        views: list[dict[str, Any]] = []
        for assignment in active:
            title, progress_label = await self._title_and_progress(
                assignment,
                summary=summaries.get(assignment.id),
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
                actor_role=actor_role,
            )
            views.append(
                {
                    "assignment": assignment,
                    "title": title,
                    "progress_label": progress_label,
                    "timezone": timezone,
                }
            )
        return views

    async def _title_and_progress(
        self,
        assignment: Assignment,
        *,
        summary: Any,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        actor_role: str,
    ) -> tuple[str, str | None]:
        if assignment.assignment_type == AssignmentType.ACKNOWLEDGEMENT.value:
            title = getattr(summary, "title", None) or "Ознакомление"
            if summary is not None:
                required = getattr(summary, "required_documents", 0)
                done = getattr(summary, "acknowledged_required_count", 0)
                return str(title), f"{done}/{required}"
            return str(title), None
        title = "Курс"
        if assignment.program_id is not None:
            try:
                program = await self._programs.get_program(
                    assignment.program_id,
                    company_id=actor_company_id,
                    actor_role=actor_role,
                    actor_employee_id=actor_employee_id,
                )
                title = program.title
            except NotFoundError:
                title = "Курс"
        percentage = await self._progress.calculate_progress_percentage(
            assignment.id, company_id=actor_company_id
        )
        return title, f"{percentage:.0f}%"

    async def _employee_timezone(
        self, company_id: UUID, employee_id: UUID
    ) -> str:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None or employee.company_id != company_id:
                raise NotFoundError(f"Employee {employee_id} not found")
            return company_timezone(
                company.timezone if company is not None else None
            )

    async def _manager_fallback(
        self, company_id: UUID, employee_id: UUID
    ) -> tuple[str, str | None] | None:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None or employee.manager_id is None:
                return None
            manager = await uow.employees.get_by_id(employee.manager_id)
            if (
                manager is None
                or manager.company_id != company_id
                or manager.status == EmployeeStatus.ARCHIVED.value
            ):
                return None
            return manager.full_name, manager.job_title


def _text_result(
    intent: AssistantIntent,
    text: str,
    *,
    used_llm: bool = False,
    metadata: dict[str, Any] | None = None,
) -> AssistantResult:
    return AssistantResult(
        kind=intent.value,
        text=text,
        intent=intent.value,
        used_llm=used_llm,
        metadata=metadata or {},
    )


def _from_chat(
    answer: ChatAnswer, intent: AssistantIntent, *, used_retriever: bool
) -> AssistantResult:
    return AssistantResult(
        kind=intent.value,
        text=answer.answer,
        intent=intent.value,
        conversation_id=answer.conversation_id,
        citations=answer.citations,
        no_answer=answer.no_answer,
        used_retriever=used_retriever,
        used_llm=True,
    )


def _responsibility_text(mapped: ResponsibilityResult) -> str:
    return format_responsibility(
        topic_name=mapped.topic_name,
        department_name=mapped.department_name,
        employee_full_name=mapped.employee_full_name,
        employee_job_title=mapped.employee_job_title,
    )


def _step_excerpt(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    description = fields.get("description")
    if isinstance(description, str) and description.strip():
        parts.append(description.strip())
    content = fields.get("content")
    for block in normalize_step_content(content if isinstance(content, dict) else None):
        if block.text.strip():
            parts.append(block.text.strip())
    questions = content.get("questions") if isinstance(content, dict) else None
    if isinstance(questions, list):
        for item in questions:
            if isinstance(item, dict):
                text = item.get("text") or item.get("prompt")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
    return "\n\n".join(parts)[:4000]
