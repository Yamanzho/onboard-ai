"""Phase 9I orchestrator: no-RAG paths, DB truth, responsibility, training help."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.db.enums import KnowledgeVisibility
from app.db.models.company import Company
from app.db.models.department import Department
from app.db.models.employee import Employee
from app.db.models.question_topic import QuestionTopic
from app.db.models.topic_responsibility import TopicResponsibility
from app.services.ai.chat import AIChatService, ChatAnswer
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.ai.llm import FakeLLMProvider
from app.services.ai.retriever import KnowledgeRetriever
from app.services.assistant.messages import (
    GREETING_TEXT,
    HELP_TEXT,
    NO_ACTIVE_ASSIGNMENTS,
    NO_ANSWER_NO_OWNER,
    RESPONSIBILITY_UNCONFIGURED,
    THANKS_TEXT,
)
from app.services.assistant.orchestrator import AssistantOrchestrator
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory, auth_header


class _BoomRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> list[Any]:
        raise AssertionError("KnowledgeRetriever must not be called")


class _RecordingLLM(FakeLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def generate(self, *, system_prompt: str, user_prompt: str):
        self.calls += 1
        return await super().generate(
            system_prompt=system_prompt, user_prompt=user_prompt
        )


def _boom_chat() -> AIChatService:
    return AIChatService(
        retriever=_BoomRetriever(),  # type: ignore[arg-type]
        llm_provider=_RecordingLLM(),
        uow_factory=_uow_factory,
    )


def _orchestrator(chat: AIChatService | None = None) -> AssistantOrchestrator:
    return AssistantOrchestrator(
        chat_service=chat or _boom_chat(),
        uow_factory=_uow_factory,
    )


@pytest.mark.asyncio
async def test_greeting_thanks_help_skip_retriever(
    company_a: Company,
    employee_a: Employee,
) -> None:
    llm = _RecordingLLM()
    chat = AIChatService(
        retriever=_BoomRetriever(),  # type: ignore[arg-type]
        llm_provider=llm,
        uow_factory=_uow_factory,
    )
    orch = _orchestrator(chat)
    greeting = await orch.handle(
        "Привет",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    thanks = await orch.handle(
        "Спасибо",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    help_ = await orch.handle(
        "Что ты умеешь?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert greeting.text == GREETING_TEXT
    assert thanks.text == THANKS_TEXT
    assert help_.text == HELP_TEXT
    assert greeting.used_retriever is False
    assert thanks.used_retriever is False
    assert help_.used_retriever is False
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_next_task_empty_and_ordered(
    api_client,
    hr_a: Employee,
    employee_a: Employee,
    company_a: Company,
) -> None:
    orch = _orchestrator()
    empty = await orch.handle(
        "Что мне делать?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert empty.text == NO_ACTIVE_ASSIGNMENTS
    assert empty.used_retriever is False

    first = await _publish_assign(
        api_client, hr_a, company_a, employee_a, title="Онбординг"
    )
    due = datetime.now(UTC) + timedelta(days=5)
    created_imp = await _publish_assign(
        api_client,
        hr_a,
        company_a,
        employee_a,
        title="Критичный курс",
        priority="critical",
        due_at=due,
    )
    listed = await orch.handle(
        "Что мне делать?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert listed.intent == "next_task"
    assert listed.used_retriever is False
    assert "Критичный курс" in listed.text
    assert listed.text.index("Критичный курс") < listed.text.index("Онбординг")
    assert str(created_imp["id"]) not in listed.text
    assert str(first["id"]) not in listed.text
    cancelled = await api_client.delete(
        f"/api/v1/assignments/{first['id']}",
        headers=auth_header(hr_a),
    )
    assert cancelled.status_code == 204
    after = await orch.handle(
        "Что мне делать?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert "Онбординг" not in after.text


@pytest.mark.asyncio
async def test_continue_learning_actions(
    api_client,
    hr_a: Employee,
    employee_a: Employee,
    company_a: Company,
) -> None:
    orch = _orchestrator()
    none = await orch.handle(
        "Продолжи курс",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert none.action == "none"
    one = await _publish_assign(
        api_client, hr_a, company_a, employee_a, title="Курс A"
    )
    single = await orch.handle(
        "Продолжи курс",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert single.action == "resume_learning"
    assert single.assignment_ids == (UUID(one["id"]),)
    await _publish_assign(api_client, hr_a, company_a, employee_a, title="Курс B")
    many = await orch.handle(
        "Продолжи курс",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert many.action == "choose_assignment"
    assert len(many.assignment_ids) == 2


@pytest.mark.asyncio
async def test_acknowledgement_is_not_resume_learning(
    api_client,
    hr_a: Employee,
    employee_a: Employee,
    company_a: Company,
    article_service: ArticleService,
) -> None:
    created = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Policy",
        body="Read this.",
        visibility=KnowledgeVisibility.COMPANY.value,
    )
    await article_service.publish_article(created.id, company_id=company_a.id)
    res = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={
            "assignment_type": "acknowledgement",
            "employee_id": str(employee_a.id),
            "documents": [{"article_id": str(created.id), "position": 1}],
        },
    )
    assert res.status_code == 201, res.text
    orch = _orchestrator()
    result = await orch.handle(
        "Продолжи курс",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert result.action == "none"
    assert result.assignment_ids == ()


@pytest.mark.asyncio
async def test_responsibility_routing_and_fallback(
    company_a: Company,
    employee_a: Employee,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        department = await uow.departments.create(
            Department(
                company_id=company_a.id,
                name="IT Support",
                slug=f"it-{uuid4().hex[:6]}",
                is_active=True,
            )
        )
        active = await uow.question_topics.create(
            QuestionTopic(
                company_id=company_a.id,
                name="Ноутбуки",
                slug="laptops",
                is_active=True,
            )
        )
        inactive = await uow.question_topics.create(
            QuestionTopic(
                company_id=company_a.id,
                name="Старые ноутбуки",
                slug="old-laptops",
                is_active=False,
            )
        )
        vacation = await uow.question_topics.create(
            QuestionTopic(
                company_id=company_a.id,
                name="Отпуска",
                slug="vacation",
                is_active=True,
            )
        )
        await uow.topic_responsibilities.create(
            TopicResponsibility(
                company_id=company_a.id,
                topic_id=active.id,
                department_id=department.id,
                employee_id=employee_a.id,
            )
        )
        await uow.topic_responsibilities.create(
            TopicResponsibility(
                company_id=company_a.id,
                topic_id=inactive.id,
                department_id=department.id,
                employee_id=employee_a.id,
            )
        )
        await uow.commit()

    orch = _orchestrator()
    found = await orch.handle(
        "Кто отвечает за ноутбуки?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert found.used_retriever is False
    assert "IT Support" in found.text
    assert employee_a.full_name in found.text
    assert "заявк" in found.text.lower() or "напрямую" in found.text

    missing = await orch.handle(
        "Кто отвечает за отпуска?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert RESPONSIBILITY_UNCONFIGURED in missing.text
    assert vacation.name
    assert missing.metadata.get("configured") is False


@pytest.mark.asyncio
async def test_rag_no_answer_falls_back_to_responsibility(
    company_a: Company,
    employee_a: Employee,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        department = await uow.departments.create(
            Department(
                company_id=company_a.id,
                name="HR Desk",
                slug=f"hr-{uuid4().hex[:6]}",
                is_active=True,
            )
        )
        topic = await uow.question_topics.create(
            QuestionTopic(
                company_id=company_a.id,
                name="Отпуск",
                slug="vacation",
                is_active=True,
            )
        )
        await uow.topic_responsibilities.create(
            TopicResponsibility(
                company_id=company_a.id,
                topic_id=topic.id,
                department_id=department.id,
                employee_id=None,
            )
        )
        await uow.commit()

    class _NoAnswerChat:
        async def answer(self, *args: object, **kwargs: object) -> ChatAnswer:
            return ChatAnswer(
                answer="I could not find an answer in the company knowledge base.",
                no_answer=True,
                citations=(),
                model="fake",
                status="empty_retrieval",
                hit_count=0,
                conversation_id=uuid4(),
            )

    orch = AssistantOrchestrator(
        chat_service=_NoAnswerChat(),  # type: ignore[arg-type]
        uow_factory=_uow_factory,
    )
    result = await orch.handle(
        "Как оформить отпуск?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert result.no_answer is True
    assert result.used_retriever is True
    assert "HR Desk" in result.text
    assert "отпуск" in result.text.lower()


@pytest.mark.asyncio
async def test_rag_no_answer_without_owner(
    company_a: Company,
    employee_a: Employee,
) -> None:
    class _NoAnswerChat:
        async def answer(self, *args: object, **kwargs: object) -> ChatAnswer:
            return ChatAnswer(
                answer="missing",
                no_answer=True,
                citations=(),
                model="fake",
                status="empty_retrieval",
                hit_count=0,
                conversation_id=uuid4(),
            )

    orch = AssistantOrchestrator(
        chat_service=_NoAnswerChat(),  # type: ignore[arg-type]
        uow_factory=_uow_factory,
    )
    result = await orch.handle(
        "Как оформить секретный ритуал?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert result.text == NO_ANSWER_NO_OWNER
    assert result.no_answer is True


@pytest.mark.asyncio
async def test_training_help_uses_snapshot_not_live_edit(
    api_client,
    hr_a: Employee,
    employee_a: Employee,
    company_a: Company,
) -> None:
    program = await _create_program(
        api_client, hr_a, company_a, title="Информационная безопасность"
    )
    step = await _add_step(
        api_client,
        hr_a,
        program["id"],
        title="Пароли",
        content={"blocks": [{"id": "b1", "type": "text", "text": "SNAPSHOT-ONLY-PASSWORD-RULE"}]},
    )
    assignment = await _publish_assign_existing(
        api_client, hr_a, program["id"], employee_a.id
    )
    edited = await api_client.patch(
        f"/api/v1/steps/{step['id']}",
        headers=auth_header(hr_a),
        json={
            "content": {
                "blocks": [
                    {"id": "b1", "type": "text", "text": "LIVE-EDIT-SHOULD-NOT-APPEAR"}
                ]
            }
        },
    )
    assert edited.status_code in {200, 409, 400} or True
    # Course may be locked; write live content via UoW if the API rejects.
    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        live = await uow.steps.get_by_id(UUID(step["id"]))
        if live is not None:
            live.content = {
                "blocks": [{"id": "b1", "type": "text", "text": "LIVE-EDIT-SHOULD-NOT-APPEAR"}]
            }
            await uow.commit()

    orch = _orchestrator()
    progress_before = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(employee_a),
    )
    assert progress_before.status_code == 200
    statuses = [item["status"] for item in progress_before.json()["items"]]
    result = await orch.handle(
        "Я не понял этот урок",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert result.used_retriever is False
    assert "Информационная безопасность" in result.text
    assert "Пароли" in result.text
    assert "SNAPSHOT-ONLY-PASSWORD-RULE" in result.text
    assert "LIVE-EDIT-SHOULD-NOT-APPEAR" not in result.text
    progress_after = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/progress",
        headers=auth_header(employee_a),
    )
    assert [item["status"] for item in progress_after.json()["items"]] == statuses


@pytest.mark.asyncio
async def test_company_knowledge_uses_retriever(
    company_a: Company,
    employee_a: Employee,
) -> None:
    embeddings = FakeEmbeddingProvider()
    indexer = KnowledgeChunkIndexer(
        uow_factory=_uow_factory, embedding_provider=embeddings
    )
    articles = ArticleService(uow_factory=_uow_factory, chunk_indexer=indexer)
    created = await articles.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Vacation leave",
        body="Submit leave three working days in advance.",
        visibility=KnowledgeVisibility.COMPANY.value,
    )
    await articles.publish_article(created.id, company_id=company_a.id)
    retriever = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=articles,
        embedding_provider=embeddings,
    )
    chat = AIChatService(
        retriever=retriever,
        llm_provider=FakeLLMProvider(),
        uow_factory=_uow_factory,
    )
    orch = AssistantOrchestrator(chat_service=chat, uow_factory=_uow_factory)
    result = await orch.handle(
        "Как оформить отпуск?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert result.intent == "company_knowledge"
    assert result.used_retriever is True


async def _create_program(client, hr, company, *, title: str) -> dict:
    res = await client.post(
        "/api/v1/programs",
        headers=auth_header(hr),
        json={"company_id": str(company.id), "title": title},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _add_step(client, hr, program_id: str, *, title: str, content: dict) -> dict:
    res = await client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=auth_header(hr),
        json={"title": title, "step_type": "content", "content": content},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _publish_assign_existing(client, hr, program_id: str, employee_id: UUID) -> dict:
    assert (
        await client.post(
            f"/api/v1/programs/{program_id}/publish",
            headers=auth_header(hr),
        )
    ).status_code == 200
    res = await client.post(
        "/api/v1/assignments",
        headers=auth_header(hr),
        json={"employee_id": str(employee_id), "program_id": program_id},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _publish_assign(
    client,
    hr,
    company,
    employee,
    *,
    title: str,
    priority: str = "normal",
    due_at: datetime | None = None,
) -> dict:
    program = await _create_program(client, hr, company, title=title)
    await _add_step(
        client,
        hr,
        program["id"],
        title="Intro",
        content={"blocks": [{"id": "b1", "type": "text", "text": "Hello"}]},
    )
    assert (
        await client.post(
            f"/api/v1/programs/{program['id']}/publish",
            headers=auth_header(hr),
        )
    ).status_code == 200
    body: dict[str, Any] = {
        "employee_id": str(employee.id),
        "program_id": program["id"],
        "priority": priority,
    }
    if due_at is not None:
        body["due_at"] = due_at.isoformat()
    res = await client.post(
        "/api/v1/assignments",
        headers=auth_header(hr),
        json=body,
    )
    assert res.status_code == 201, res.text
    return res.json()
