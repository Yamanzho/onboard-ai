"""Synthetic AI-7 retrieval corpus. No secrets, no employee PII, no production data."""

from __future__ import annotations

from dataclasses import dataclass

from app.db.enums import KnowledgeBodyFormat, KnowledgeVisibility
from app.services.ai.chunking import chunk_article

COMPANY_A = "a"
COMPANY_B = "b"


@dataclass(frozen=True, slots=True)
class EvalArticle:
    key: str
    company: str
    title: str
    body: str
    language: str
    body_format: str = KnowledgeBodyFormat.MARKDOWN.value
    visibility: str = KnowledgeVisibility.COMPANY.value
    chunking: str | None = None


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: str
    question: str
    language: str
    expected_keys: tuple[str, ...]
    expect_no_answer: bool = False
    cross_language: bool = False
    exact_phrase: bool = False
    expected_chunk_index: int | None = None
    target_language: str | None = None


def _repeat_sections(blocks: list[str], times: int) -> str:
    parts: list[str] = []
    for index in range(times):
        for block in blocks:
            parts.append(block.replace("{n}", str(index + 1)))
    return "\n\n".join(parts)


_CONDUCT_RU = _repeat_sections(
    [
        "## Раздел {n}. Уважение к коллегам\n\n"
        "Сотрудник OnboardAI Demo не повышает голос на встречах, не шутит над "
        "национальностью и не обсуждает зарплату другого человека без его согласия. "
        "Жалобы направляются в HR на адрес hr-demo@onboard.example.",
        "## Раздел {n}. Конфликт интересов\n\n"
        "Запрещено принимать подарки дороже 20 000 тенге от подрядчиков. "
        "О конфликтах сообщают руководителю в течение двух рабочих дней.",
        "## Раздел {n}. Рабочее место\n\n"
        "- не оставляйте пропуска на ресепшен без записи\n"
        "- кухня убирается после себя\n"
        "- переговорные бронируются в календаре\n",
        "| Тема | Правило | Штраф |\n|---|---|---|\n"
        "| Опоздание | предупредить в чате команды | замечание |\n"
        "| Разглашение | клиентские списки | дисциплинарное |\n",
    ],
    times=3,
)

_ONBOARDING_EN = """
# First week handbook

Welcome to OnboardAI Demo. Your buddy will message you on day one.

## Day 1

- Collect the building pass at reception on floor 1
- Join Slack workspace `onboardai-demo`
- Read the vacation, VPN, and NDA articles in this knowledge base

## Day 2–3

Complete the IT checklist: laptop disk encryption, password manager, and
VPN profile. File a ticket in Slack channel `#it-help` if the WireGuard
profile is missing.

## Day 4–5

Shadow your team stand-up. Add `remote` to your calendar status when you
work from home. Remote work is at most two days per week unless HR approves
an exception.

## Useful table

| Day | Owner | Checkpoint |
|---|---|---|
| 1 | Office | Badge collected |
| 2 | IT | VPN connected |
| 3 | HR | Policies acknowledged |
| 5 | Manager | First-week recap |
""".strip()

EVAL_ARTICLES: tuple[EvalArticle, ...] = (
    EvalArticle(
        key="leave-ru",
        company=COMPANY_A,
        language="ru",
        title="Отпуск",
        body=(
            "Сотрудник подаёт заявление на ежегодный отпуск не позднее чем за "
            "три рабочих дня. Согласование делает непосредственный руководитель, "
            "затем HR вносит даты в график. Экстренный отпуск по семейным "
            "обстоятельствам согласуется в тот же день письмом на hr-demo@onboard.example."
        ),
    ),
    EvalArticle(
        key="leave-kk",
        company=COMPANY_A,
        language="kk",
        title="Демалыс",
        body=(
            "Қызметкер жыл сайынғы демалысқа өтінішті кемінде үш жұмыс күні бұрын "
            "береді. Келісімді тікелей басшы береді, содан кейін HR күндерді "
            "кестеге енгізеді. Отбасылық жағдай бойынша шұғыл демалыс сол күні "
            "hr-demo@onboard.example поштасына хатпен келісіледі."
        ),
    ),
    EvalArticle(
        key="leave-en",
        company=COMPANY_A,
        language="en",
        title="Vacation leave",
        body=(
            "Submit an annual leave request at least three working days in advance. "
            "Your manager approves first, then HR records the dates. Emergency "
            "family leave can be approved the same day by emailing "
            "hr-demo@onboard.example."
        ),
    ),
    EvalArticle(
        key="vpn-ru",
        company=COMPANY_A,
        language="ru",
        title="Доступ к VPN",
        body=(
            "Удалённый доступ идёт через WireGuard. Заявку создайте в Slack-канале "
            "#it-help. Из офисной сети VPN не обязателен. Сертификат действует "
            "90 дней, продление — повторный тикет в IT."
        ),
    ),
    EvalArticle(
        key="vpn-en",
        company=COMPANY_A,
        language="en",
        title="VPN access",
        body=(
            "Remote access uses WireGuard. Open a ticket in Slack channel #it-help. "
            "VPN is not required on the office LAN. Profiles expire after 90 days; "
            "renew by filing another IT ticket."
        ),
    ),
    EvalArticle(
        key="sick-ru",
        company=COMPANY_A,
        language="ru",
        title="Больничный",
        body=(
            "В первый день болезни напишите руководителю в рабочий чат. "
            "Электронную справку загрузите в HR-портал в течение трёх календарных "
            "дней. Оплата идёт по больничному листу, самолечение без справки не "
            "оплачивается."
        ),
    ),
    EvalArticle(
        key="hours-kk",
        company=COMPANY_A,
        language="kk",
        title="Жұмыс уақыты",
        body=(
            "Офис дүйсенбі–жұма сағат 09:00–18:00 жұмыс істейді. Түскі үзіліс "
            "13:00–14:00. Кешігу туралы команда чатына алдын ала жазыңыз. "
            "Жұма күні 17:00-ден кейін міндетті жиналыс жоқ."
        ),
    ),
    EvalArticle(
        key="equipment-en",
        company=COMPANY_A,
        language="en",
        title="Laptop and equipment",
        body=(
            "Return the laptop, charger, and headset on your last working day to "
            "IT on floor 2. Do not wipe the disk yourself. Lost chargers are "
            "replaced after an #it-help ticket; personal stickers on lids are fine."
        ),
    ),
    EvalArticle(
        key="expenses-ru",
        company=COMPANY_A,
        language="ru",
        title="Командировочные расходы",
        body=(
            "Чеки по командировке загружайте в Concur в течение пяти рабочих дней "
            "после возвращения. Суточные — 15 000 тенге в Казахстане. Такси до "
            "аэропорта согласовывается заранее с руководителем. Алкоголь не "
            "компенсируется."
        ),
    ),
    EvalArticle(
        key="wifi-en",
        company=COMPANY_A,
        language="en",
        title="Guest Wi-Fi",
        body=(
            "Visitors use the guest network named OnboardGuest. Ask reception on "
            "floor 1 for the daily guest code. Do not share the employee Wi-Fi. "
            "The guest network blocks SMB and internal admin tools."
        ),
        chunking="short",
    ),
    EvalArticle(
        key="onboarding-en",
        company=COMPANY_A,
        language="en",
        title="First week handbook",
        body=_ONBOARDING_EN,
        chunking="medium",
    ),
    EvalArticle(
        key="conduct-ru",
        company=COMPANY_A,
        language="ru",
        title="Кодекс поведения",
        body=_CONDUCT_RU,
        chunking="long",
    ),
    EvalArticle(
        key="helpdesk-en",
        company=COMPANY_A,
        language="en",
        title="IT Helpdesk",
        body=(
            "IT support lives in Slack channel #it-help. Priority-1 outages "
            "(email or VPN down for everyone) have a four-hour response SLA. "
            "Password resets for the work account are done by IT, never by "
            "asking a teammate to share a password."
        ),
    ),
    EvalArticle(
        key="remote-en",
        company=COMPANY_A,
        language="en",
        title="Remote work",
        body=(
            "Employees may work remotely at most two days per week. Mark the "
            "calendar status as remote before 09:00. Core hours 11:00–16:00 "
            "Almaty time remain mandatory. Full-remote needs a written HR exception."
        ),
    ),
    EvalArticle(
        key="probation-kk",
        company=COMPANY_A,
        language="kk",
        title="Сынақ мерзімі",
        body=(
            "Сынақ мерзімі үш ай. Бірінші айдың соңында басшы қысқа кері байланыс "
            "береді. Мерзімді ұзарту тек HR жазбаша келісімімен болады. Сынақ "
            "кезінде жылдық демалыс келісіледі, бірақ алдын ала төленбейді."
        ),
    ),
    EvalArticle(
        key="fire-ru",
        company=COMPANY_A,
        language="ru",
        title="Пожарная безопасность",
        body=(
            "При пожарной тревоге не пользуйтесь лифтом. Выходите по лестнице А "
            "к парковке у главного входа — это точка сбора. Сообщите о людях, "
            "оставшихся на этаже, охране. Огнетушители — у лифтового холла."
        ),
    ),
    EvalArticle(
        key="nda-en",
        company=COMPANY_A,
        language="en",
        title="Confidentiality",
        body=(
            "Do not share client lists, salary bands, or unpublished roadmap "
            "slides outside the company. Public blog posts need marketing review. "
            "Personal cloud drives are not an approved store for customer files."
        ),
    ),
    EvalArticle(
        key="badge-kk",
        company=COMPANY_A,
        language="kk",
        title="Кеңсе бэджі",
        body=(
            "Бэджді бірінші қабаттағы ресепшеннен алыңыз. Жоғалған бэджді сол "
            "күні күзетке хабарлаңыз — картаны бұғаттайды. Қонаққа бір күндік "
            "өткізуді қабылдаушы шығарады, қызметкер оны ертіп жүреді."
        ),
    ),
    EvalArticle(
        key="payroll-ru",
        company=COMPANY_A,
        language="ru",
        title="Зарплата",
        body=(
            "Заработная плата — выплата десятого числа каждого месяца на зарплатную "
            "карту. Если 10-е выпадает на выходной, перевод делают в предыдущий "
            "рабочий день. Расчётный лист смотрите в HR-портале, не в открытом чате."
        ),
    ),
    EvalArticle(
        key="meetings-en",
        company=COMPANY_A,
        language="en",
        title="Meeting rooms",
        body=(
            "Book rooms in the shared calendar. Do not hold stand-ups in the "
            "quiet zone.\n\n"
            "| Room | Floor | Seats |\n"
            "|---|---|---|\n"
            "| Alatau | 2 | 6 |\n"
            "| Medeu | 2 | 12 |\n"
            "| Esentai | 3 | 4 |\n\n"
            "Cancel the booking if you finish more than 15 minutes early."
        ),
        chunking="table",
    ),
    EvalArticle(
        key="bonus-b-en",
        company=COMPANY_B,
        language="en",
        title="Company B annual bonus formula",
        body=(
            "Company B pays an annual bonus equal to 18 percent of base salary "
            "when the Northwind product line beats the Q4 target. This formula "
            "is unique to Company B and must never appear in Company A retrieval."
        ),
    ),
)

_LEAVE = ("leave-ru", "leave-kk", "leave-en")
_VPN = ("vpn-en", "vpn-ru")


def _identity_question(key: str) -> str:
    """Full indexed chunk text. Fake embeddings only match this, not substrings."""
    article = next(item for item in EVAL_ARTICLES if item.key == key)
    chunks = chunk_article(
        title=article.title,
        body=article.body,
        body_format=article.body_format,
    )
    if len(chunks) != 1:
        raise RuntimeError(f"identity fixture {key} must be a single chunk")
    return chunks[0]


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase("ru-leave-how", "Как оформить отпуск?", "ru", _LEAVE),
    EvalCase(
        "ru-leave-deadline",
        "За сколько дней нужно подать заявление на отпуск?",
        "ru",
        ("leave-ru", *_LEAVE[1:]),
    ),
    EvalCase("ru-sick", "Что делать если я заболел и нужен больничный?", "ru", ("sick-ru",)),
    EvalCase(
        "ru-expenses",
        "Куда загрузить чеки из командировки?",
        "ru",
        ("expenses-ru",),
    ),
    EvalCase("ru-fire", "Куда бежать при пожарной тревоге?", "ru", ("fire-ru",)),
    EvalCase("ru-payroll", "Когда приходит зарплата?", "ru", ("payroll-ru",)),
    EvalCase(
        "ru-conduct",
        "Что кодекс поведения запрещает в подарках подрядчикам?",
        "ru",
        ("conduct-ru",),
    ),
    EvalCase("ru-vpn-office", "Нужен ли VPN из офисной сети?", "ru", _VPN),
    EvalCase(
        "kk-leave",
        "Демалысқа қалай өтініш беремін?",
        "kk",
        ("leave-kk", "leave-ru", "leave-en"),
    ),
    EvalCase("kk-hours", "Жұмыс қай сағатта басталады?", "kk", ("hours-kk",)),
    EvalCase("kk-probation", "Сынақ мерзімі қанша ай?", "kk", ("probation-kk",)),
    EvalCase("kk-badge", "Бэдж жоғалса не істеймін?", "kk", ("badge-kk",)),
    EvalCase(
        "en-vpn",
        "How do I connect to the company VPN?",
        "en",
        _VPN,
    ),
    EvalCase(
        "en-wifi",
        "How do visitors get on guest Wi-Fi?",
        "en",
        ("wifi-en",),
    ),
    EvalCase(
        "en-equipment",
        "When do I return the laptop?",
        "en",
        ("equipment-en",),
    ),
    EvalCase(
        "en-remote",
        "How many remote days per week are allowed?",
        "en",
        ("remote-en",),
    ),
    EvalCase(
        "en-helpdesk",
        "Where do I ask IT for help?",
        "en",
        ("helpdesk-en",),
    ),
    EvalCase(
        "en-nda",
        "Can I share the client list with a friend?",
        "en",
        ("nda-en",),
    ),
    EvalCase(
        "en-onboarding",
        "What happens in the first week of onboarding?",
        "en",
        ("onboarding-en",),
    ),
    EvalCase(
        "en-meetings",
        "Which meeting room seats twelve people?",
        "en",
        ("meetings-en",),
    ),
    EvalCase(
        "cross-ru-en-vpn",
        "Как подключить VPN WireGuard?",
        "ru",
        ("vpn-en", "vpn-ru"),
        cross_language=True,
        target_language="en",
    ),
    EvalCase(
        "cross-en-ru-leave",
        "How do I request vacation leave in this company?",
        "en",
        ("leave-ru", "leave-en", "leave-kk"),
        cross_language=True,
        target_language="ru",
    ),
    EvalCase(
        "cross-kk-ru-leave",
        "Демалыс өтінішін қайда беремін?",
        "kk",
        ("leave-ru", "leave-kk", "leave-en"),
        cross_language=True,
        target_language="ru",
    ),
    EvalCase(
        "cross-ru-kk-hours",
        "Какой график работы в офисе?",
        "ru",
        ("hours-kk",),
        cross_language=True,
        target_language="kk",
    ),
    EvalCase(
        "cross-en-kk-probation",
        "What is the probation period length in months?",
        "en",
        ("probation-kk",),
        cross_language=True,
        target_language="kk",
    ),
    EvalCase(
        "cross-kk-en-laptop",
        "Ноутбукты қашан қайтарамын?",
        "kk",
        ("equipment-en",),
        cross_language=True,
        target_language="en",
    ),
    EvalCase(
        "cross-en-ru-fire",
        "Where is the fire assembly point?",
        "en",
        ("fire-ru",),
        cross_language=True,
        target_language="ru",
    ),
    EvalCase(
        "cross-kk-ru-sick",
        "Больничный қалай рәсімделеді?",
        "kk",
        ("sick-ru",),
        cross_language=True,
        target_language="ru",
    ),
    EvalCase(
        "cross-kk-en-wifi",
        "Қонақтарға Wi-Fi қалай беріледі?",
        "kk",
        ("wifi-en",),
        cross_language=True,
        target_language="en",
    ),
    EvalCase(
        "identity-wifi",
        _identity_question("wifi-en"),
        "en",
        ("wifi-en",),
        exact_phrase=True,
    ),
    EvalCase(
        "identity-payroll",
        _identity_question("payroll-ru"),
        "ru",
        ("payroll-ru",),
        exact_phrase=True,
    ),
    EvalCase(
        "identity-probation",
        _identity_question("probation-kk"),
        "kk",
        ("probation-kk",),
        exact_phrase=True,
    ),
    EvalCase(
        "na-bread",
        "How do I bake sourdough bread at home?",
        "en",
        (),
        expect_no_answer=True,
    ),
    EvalCase(
        "na-ceo-pay",
        "Какая зарплата у генерального директора лично?",
        "ru",
        (),
        expect_no_answer=True,
    ),
    EvalCase(
        "na-crypto",
        "Криптобиржада аккаунтты қалай ашамын?",
        "kk",
        (),
        expect_no_answer=True,
    ),
    EvalCase(
        "na-k8s",
        "What is the Kubernetes ingress timeout in production?",
        "en",
        (),
        expect_no_answer=True,
    ),
    EvalCase(
        "na-visa",
        "Как получить туристическую визу в Японию?",
        "ru",
        (),
        expect_no_answer=True,
    ),
    EvalCase(
        "na-yacht",
        "Where does the company park the yacht?",
        "en",
        (),
        expect_no_answer=True,
    ),
    EvalCase(
        "na-gmail",
        "How do I reset my personal Gmail password?",
        "en",
        (),
        expect_no_answer=True,
    ),
    EvalCase(
        "na-factory",
        "Как закупить промышленные станки для цеха?",
        "ru",
        (),
        expect_no_answer=True,
    ),
    EvalCase(
        "en-helpdesk-sla",
        "What is the IT outage response SLA in Slack?",
        "en",
        ("helpdesk-en",),
    ),
    EvalCase(
        "ru-expenses-per-diem",
        "Какие суточные в командировке по Казахстану?",
        "ru",
        ("expenses-ru",),
    ),
)

CHUNKING_HTML_RU = EvalArticle(
    key="html-ru",
    company=COMPANY_A,
    language="ru",
    title="HTML-памятка",
    body=(
        "<h1>Памятка</h1><p>Сотрудник читает <strong>политику</strong>.</p>"
        "<script>alert(1)</script><p>Қосымша мәтін үшін қазақ әріптері: ғұқөң.</p>"
    ),
    body_format=KnowledgeBodyFormat.HTML.value,
    chunking="html",
)

CHUNKING_KK_BULLETS = EvalArticle(
    key="kk-bullets",
    company=COMPANY_A,
    language="kk",
    title="Кеңсе ережелері",
    body=(
        "# Кеңсе\n\n"
        "- Бэдж көрініп тұруы керек\n"
        "- Қонақты ресепшенде тіркеңіз\n"
        "- Түнгі шығу күзетке хабарланады\n\n"
        "Қосымша: ә, ғ, қ, ң, ө, ү, ұ, і, һ."
    ),
    chunking="bullets",
)


def articles_by_key() -> dict[str, EvalArticle]:
    return {article.key: article for article in EVAL_ARTICLES}


def answerable_cases() -> tuple[EvalCase, ...]:
    return tuple(case for case in EVAL_CASES if not case.expect_no_answer)


def no_answer_cases() -> tuple[EvalCase, ...]:
    return tuple(case for case in EVAL_CASES if case.expect_no_answer)
