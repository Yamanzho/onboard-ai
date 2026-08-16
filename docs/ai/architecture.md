# AI Assistant — architecture freeze (AI-0)

This document freezes the approved AI/RAG design. It is **not** a running
production AI feature. Later stages (AI-1+) must implement against these rules.

Existing OnboardAI architecture is unchanged: FastAPI, PostgreSQL, Redis,
Telegram-via-REST, `ArticleService` KB ACL, and tenant RLS. AI is an overlay,
not a rewrite.

## Forbidden

- Qdrant / Weaviate / Pinecone / any dedicated vector SaaS
- Treating the vector layer as ACL authority
- Indexing draft, archived, or non-current article versions
- Using AI conversation history as a knowledge source
- Super Admin AI access without tenant impersonation
- Production AI runtime in AI-0 (this file is a freeze, not a feature)

## Frozen decisions

1. **PostgreSQL + pgvector** — the only vector store. Same runtime, backup, and
   RLS model as the rest of the product.
2. **Current published KB version only** — index
   `KnowledgeArticle.current_version_id` when `status=published`. Never draft,
   archived, or historical versions.
3. **ACL-first retrieval** — compute allowed article ids **before** ANN/FTS.
   Never `retrieve all → LLM → filter`.
4. **`ArticleService` remains the authority for KB permissions** — the retriever
   must call it, not duplicate visibility / program-assignment rules.
5. **Vector storage is a retrieval acceleration layer** — not a source of truth
   and not a source of rights. Postgres articles, links, and assignments are.
6. **Telegram uses the REST API** — the bot does not query the database or call
   an LLM directly (same pattern as onboarding).
7. **AI catch-all must not intercept the onboarding FSM** — router order:
   start → onboarding (FSM) → cabinet/menu → AI last. Quiz/step replies stay
   in onboarding.
8. **AI conversation is not a KB source** — stored `AIMessage` rows are UX /
   future short-term prompt context only (not yet sent to the LLM in AI-11A).
   Every turn re-retrieves against **live** ACL. Revoked access must not be
   replayed from history.
9. **no-answer instead of hallucination** — empty allowed set, low relevance,
   or missing context → honest refusal, never a guessed policy.
10. **Citations are mandatory** — the model may cite only `article_id`s that were
    placed in context. Backend fills title / version / path from the database.
11. **Tenant isolation + RLS are mandatory** — `company_id` comes from the JWT
    or `BOT_COMPANY_ID`, never from the client. Future chunk rows use the same
    FORCE RLS pattern as KB tables.
12. **Super Admin without tenant impersonation has no AI access.**

## Security pipeline (order is mandatory)

```
AUTH
→ TENANT
→ EMPLOYEE
→ PUBLISHED
→ VISIBILITY
→ PROGRAM ACL
→ RETRIEVAL
→ CONTEXT
→ LLM
```

Breaking this order is a leak. The vector index cannot skip steps 1–6.

## Embedding abstraction (AI-1)

Application services in this repo are async classes with constructor injection
and `ValidationError` for invariants. Embeddings follow that style:

- `EmbeddingProvider` — provider-independent protocol (`embed`, `embed_batch`)
- `FakeEmbeddingProvider` — deterministic in-process implementation (dev/CI)
- `OpenAIEmbeddingProvider` — AI-6 hosted production provider
  (`text-embedding-3-small`, **1536** dimensions, httpx, no SDK)
- Default column width: **1536** (fake and hosted share this width)
- API key: `AI_EMBEDDING_API_KEY` or `OPENAI_API_KEY` (env only, `SecretStr`,
  never logged)

Fake vs hosted vectors must not be mixed in one index. Changing model or
dimension requires Alembic (if width changes) and a full tenant reindex of
**current published** versions.

| Provider | Typical dimension | Role |
|---|---|---|
| OpenAI `text-embedding-3-small` | 1536 | AI-6 production hosted default |
| OpenAI `text-embedding-3-large` | 3072 | Higher quality, higher cost |
| Azure OpenAI embeddings | 1536 / 3072 | Same models, enterprise network |
| `multilingual-e5-small` / `base` | 384 / 768 | Local multilingual |
| BGE-M3 | 1024 | Stronger KK / multilingual local option |

Changing a real model later requires a full reindex. Fake vs hosted dimensions
must not be mixed in one index.

## Automatic KB indexing (AI-3)

Vector storage is **derived data**. Source of truth remains:

- `KnowledgeArticle` / `KnowledgeArticleVersion`
- `ArticleService` ACL (visibility, program links, assignments)
- publication state (`draft` / `published` / `archived`)
- `current_version_id`

`knowledge_article_chunks` must never become a second source of truth. A later
retriever must filter to the **current published** version and re-check
ArticleService; historical chunk rows are not a grant of access.

### Lifecycle

```
CREATE (draft)     → no index
EDIT draft         → no index
PUBLISH            → commit article → synchronous index of current version
EDIT published     → new immutable current version → commit → index that version
RESTORE            → new immutable current version (existing flow)
                     → if the article is published, index the new current version
ARCHIVE            → no delete of historical chunks; article is not indexable
```

There is no separate “published v1 + draft v2” model in `ArticleService`.
Content edits of a **draft** stay draft and are not indexed. Content edits of a
**published** article advance `current_version_id` while status stays
`published`; the new current version is indexed. Previous versions’ chunks are
left immutable.

### Index version rule

`KnowledgeChunkIndexer.index_published_version` indexes a row only when:

- authenticated tenant (`actor_company_id` from JWT / `BOT_COMPANY_ID`) matches
- article `status = published`
- `current_version_id == version_id`
- article and version belong to that tenant

Rejected (not-found or validation, never a tenant switch):

- draft, archived
- old / non-current version
- foreign tenant
- caller-supplied `company_id` that does not match the actor

`company_id` from a query string or body is **claimed** and untrusted. RLS
context is always `enter_tenant(actor_company_id)`.

### Transaction semantics

Indexing is **synchronous and post-commit** (`INDEXING_RUNS_AFTER_KB_COMMIT`).

1. ArticleService publish / published-version write commits in its UnitOfWork.
2. The indexer opens a **separate** UnitOfWork and writes chunks.
3. There is no Celery / Redis queue / worker.

If step 2 fails:

- the exception is logged and **re-raised** (not swallowed);
- the HTTP/API caller does not observe success;
- the already-committed published article remains readable;
- the indexer’s UoW rolls back, so no partial chunk set is stored.

A stale derived index is therefore observable (the write API errors) rather
than silent. Manual recovery is `POST /api/v1/knowledge/articles/{id}/reindex`
(HR/Admin, JWT tenant only).

### Idempotency

Re-indexing the same `(article, current published version)` deletes that
version’s chunks and inserts the same `(version_id, chunk_index)` set. Unique
constraint `uq_knowledge_article_chunks_version_id_chunk_index` prevents
duplicates. Other versions are not deleted.

### Observability

Logger `app.kb.index` records `company_id`, `article_id`, `version_id`,
`chunk_count`, `result`, `duration_ms`. It must not log article body,
embeddings, secrets, tokens, or credentials.

## ACL-first hybrid retriever (AI-4)

Internal service: `KnowledgeRetriever.retrieve`. **No HTTP search/chat API.**
No LLM. Output is ranked `RetrievalHit` rows for a later citation renderer.

### Pipeline (mandatory)

```
AUTH
→ TENANT (JWT / BOT_COMPANY_ID — never request company_id)
→ EMPLOYEE
→ ArticleService.list_articles (published + visibility + program ACL)
→ allowed article ids
→ embed query (configured EmbeddingProvider)
→ exact pgvector cosine search **inside that id set**
→ join live current_version_id (drop historical chunks)
→ per-article cap → top-k
```

Never: tenant-wide vector search → filter unauthorized hits afterwards.
Chunk `metadata` (`visibility`, `program_ids`, `company_id`) is not ACL.

`ArticleService` remains the permission authority. The retriever does not
reimplement assignment or visibility rules.

### Current published version

Hits must have `version_id = KnowledgeArticle.current_version_id` and
`status = published`. Draft, archived, and historical version chunks may still
exist in the table; the join excludes them.

### Vector distance

Exact **cosine distance** (`<=>`). Fake embeddings are L2-normalized, so
distance is `1 - dot(u, v)`. Exposed `score` is `clamp(1 - distance, 0, 1)`
for ranking only. It is **not** calibrated semantic relevance. No HNSW/IVFFlat
index in AI-4 (corpus is small).

### Top-k and per-article cap

- Default `top_k = 5`, maximum `20`
- At most **2 chunks per article** (`MAX_CHUNKS_PER_ARTICLE_RESULT`), walking
  the cosine ranking. Typical indexed policies are 1–3 windows; two neighbors
  keep a heading with its body without dumping the whole article.

### No-answer threshold

`min_score` is optional and **unset by default**. Fake hash embeddings cannot
calibrate a production no-answer cutoff. A later stage with a real model may
filter on `score` after measuring held-out queries.

### Super Admin

Without tenant impersonation, retrieve raises `ForbiddenError`. AI-4 does not
add impersonation.

### Observability

Logger `app.kb.retrieve` records company_id, employee_id, **actor_role**,
allowed_articles, hit_count, top_k, **result/status**, duration. It must not log
the query string, chunk body, embeddings, credentials, tokens, or invite URLs.

## Retrieval security invariants (AI-5)

AI retrieval must never expose more KB content than the existing KB UI/API
already allows for the same actor:

```
AI_RETRIEVAL_ACCESS <= EXISTING_KB_ACCESS
```

1. **`ArticleService` is the ACL authority.** The only authorization path is
   `ArticleService.list_articles` → allowed article ids → retriever. There is no
   `AIACLService`, no vector-level authorization, and no metadata authorization.
2. **AI retrieval cannot exceed KB UI/API permissions.** Every returned
   `article_id` must already be visible to that actor via `list_articles`.
   Employees see published + visibility + program assignment. HR/Admin see
   tenant articles; retrieval still returns **current published** only (drafts
   listed by HR are not retrievable).
3. **Metadata is never authorization.** Chunk JSON (`visibility`, `program_ids`,
   `company_id`, `role`, `admin`, …) is a denormalized hint. Poisoned metadata
   cannot grant or deny access.
4. **Current published version only.** Historical, draft, archived, and
   non-current version chunks may remain in the table; the live
   `current_version_id` + `status=published` join excludes them. Restore creates
   a **new** current version (v3); v1/v2 chunks stay inert.
5. **Tenant comes from authenticated context.** `actor_company_id` is JWT /
   `BOT_COMPANY_ID`. Query text, article/chunk/version UUIDs, claimed
   `company_id`, and spoofed metadata cannot switch tenant. A foreign claimed
   tenant is `NotFoundError` (same as missing).
6. **Super Admin requires explicit tenant context.** Without impersonation,
   retrieve raises `ForbiddenError`. AI-5 does not add impersonation.
7. **Fake score is ranking-only.**
   `score = clamp(1 - cosine_distance, 0, 1)`. FakeEmbeddingProvider hashes are
   **not** semantic relevance.
8. **No production relevance threshold yet.** `min_score` defaults to unset.
   Do not treat a cutoff as calibrated.

Query strings are untrusted **data**: they are not instructions, SQL, or ACL.
Input limits: query ≤ 2000 characters after strip; `top_k` is an integer 1..20
(bool rejected). Empty/whitespace queries are rejected.

Reindex remains HR/Admin, JWT tenant only. Company A cannot reindex or replace
Company B chunks. Indexing failure stays on the AI-3 contract (publication
committed, exception visible, no partial chunks, historical chunks do not
become current, manual reindex recovers).

## Real embedding provider + production reindex (AI-6)

Dev/CI keeps `AI_EMBEDDING_PROVIDER=fake` (no network). Production hosted
default is OpenAI `text-embedding-3-small` (`AI_EMBEDDING_PROVIDER=openai`).

- Column: `knowledge_article_chunks.embedding vector(1536)`
- FakeEmbeddingProvider default width is **1536** so it matches the column
- Keys: `AI_EMBEDDING_API_KEY` / `OPENAI_API_KEY` — env only, never in git,
  never in logs, never in chunk metadata
- No OpenAI SDK; outbound HTTP is httpx to `/v1/embeddings`
- No LLM, no chat API, no Telegram AI
- Provider failures are `ServiceUnavailableError` (HTTP 503) or credential
  `ValidationError` — they do not leak the key or the input text

### Switching provider / after the 1536 migration

Chunk rows are derived. The AI-6 Alembic revision deletes existing `vector(8)`
rows (they cannot be recast). Rebuild current published versions per tenant:

```
POST /api/v1/knowledge/articles/reindex-published
```

or

```
python -m scripts.reindex_published_kb --company-id <tenant-uuid>
```

Same tenant rules as single-article reindex: JWT/`--company-id` is the only
RLS authority; spoofed `company_id` is not-found; Employee is forbidden;
Super Admin is `ForbiddenError` without impersonation.

## Retrieval evaluation (AI-7)

AI-7 measures whether `KnowledgeRetriever` finds the intended **current
published** article for realistic employee questions. It does **not** add an
LLM, chat API, Telegram AI, public `/ai/search` route, ANN index, or a
production `min_score`.

### Methodology

- Synthetic corpus + 30–50 queries in `app/services/ai/eval_corpus.py` (RU, KK,
  EN, plus cross-language). No production data, secrets, or employee PII.
- Evaluation seeds articles through `ArticleService` (publish → index) and
  queries the **existing** `KnowledgeRetriever`. There is no evaluation-only
  ACL path, no direct chunk table scan, and no RLS bypass.
- Tenant isolation is part of the suite: Company B articles must never appear
  in Company A hits (`AI_RETRIEVAL_ACCESS <= EXISTING_KB_ACCESS`).
- CI uses `FakeEmbeddingProvider`. Live `OpenAIEmbeddingProvider` evaluation is
  opt-in (`ONBOARDAI_AI7_LIVE_OPENAI=1` +
  `python -m scripts.evaluate_kb_retrieval --live-openai`). Pytest never
  requires an API key. Embeddings are batched and disk-cached when live eval
  runs.

### Recall@K

Article-level hit: an acceptable `article_id` appears in the top-k retrieval
hits. Primary metrics are Recall@1, Recall@3, Recall@5. Top-k analysis also
reports Recall@10. Exact `chunk_index` is **not** required unless a fixture
sets it. Production default `top_k` is unchanged.

### No-answer evaluation

The dataset includes questions whose topic is absent from the KB. The report
counts `NO_ANSWER_CASES` and whether retrieval still returned nearest-neighbor
hits. Without a production threshold, a non-empty allowed corpus still yields
ranked chunks.

### Threshold analysis

Candidate floors 0.30, 0.35, …, 0.90 are scored for TP/FP/FN/TN, precision,
and recall. This is **analysis only**. No production relevance threshold is
selected or enabled (`min_score` stays unset).

### Multilingual evaluation

Metrics are grouped by query language (RU / KK / EN) and for the
cross-language subset. Quality is measured, not inferred from the model name.

### Chunking evaluation

Fixtures cover short / medium / long articles, Markdown headings, bullets,
tables, HTML, and RU/KK/EN unicode. Checks: chunk count, title prefix,
overlap, no content loss, no unicode corruption, article/version association.
The chunker is not redesigned unless evaluation proves a defect.

Measured numbers live in `docs/ai/ai7-retrieval-evaluation.md` (regenerate
with the eval script; do not invent metrics).

## Real hosted retrieval evaluation (AI-8)

AI-8 measures the same synthetic 42-case corpus through the production
`KnowledgeRetriever` using OpenAI `text-embedding-3-small` (**1536**
dimensions). It does **not** add an LLM, chat API, Telegram AI, public
`/ai/search` or `/ai/chat` route, ANN/HNSW index, or a production
`min_score`.

### Opt-in

```
ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_kb_retrieval --live-openai
```

Requires `AI_EMBEDDING_API_KEY` or `OPENAI_API_KEY`. Pytest never requires
a key. CI never sets `ONBOARDAI_AI7_LIVE_OPENAI` and never runs the eval
script. Application startup does not import or execute evaluation.

### Isolation

- Evaluation seeds disposable Company A / Company B tenants and deletes them
- Corpus is synthetic (`app/services/ai/eval_corpus.py`) — no production
  employee PII
- Embedding cache: `.ai7_embedding_cache/` (gitignored, model-specific JSON,
  SHA-256 keys, `not_a_kb_index=true`, no API keys, no raw query text)
- Fake and OpenAI caches cannot overwrite each other
- Cache files are not a pgvector KB index and must not be loaded as one
- `ArticleService` remains the only KB authorization authority

### Findings

Numbers belong in `docs/ai/ai8-real-retrieval-evaluation.md` and must be
labeled **MEASURED** or **NOT MEASURED**. FakeEmbeddingProvider is a hash
and is **not** a signal for production `min_score`, Kazakh quality, or
cross-language quality.

Production defaults stay unchanged in this stage:

- `top_k = 5`
- `min_score` unset

AI-8 live OpenAI evaluation remains NOT MEASURED (HTTP 429
`insufficient_quota` on the last opt-in run). FakeEmbeddingProvider scores
must not be used to choose a production `min_score`.

## LLM/RAG application service (AI-9A)

AI-9A adds an internal, stateless RAG service. It does **not** add an HTTP
chat route, Telegram AI, conversation persistence, or a production
`min_score`.

### Flow

```
authenticate caller
→ validate tenant / employee (actor_company_id, actor_role)
→ KnowledgeRetriever.retrieve  (ArticleService.list_articles ACL)
→ KnowledgeContextBuilder      (hits only; size limits)
→ LLMProvider.generate         (if context is non-empty)
→ structured ChatAnswer + citations
```

`AIChatService` does **not** implement ACL. ArticleService remains ACL authority.
KnowledgeRetriever remains ACL boundary. AI is not an authorization layer and
cannot access tenant data outside retrieval hits. no production min_score was
selected from FakeEmbeddingProvider or otherwise.

### LLM providers

- `LLMProvider` protocol (`generate`) — same style as `EmbeddingProvider`
- `FakeLLMProvider` — CI/default, no network
- `OpenAILLMProvider` — httpx Chat Completions (`gpt-4o-mini`), no SDK
- Settings: `AI_LLM_PROVIDER`, `AI_LLM_MODEL`, `AI_LLM_API_KEY`
  (`OPENAI_API_KEY` alias). Keys are `SecretStr`, never logged.

Pytest forces `AI_LLM_PROVIDER=fake`. Tests never call the live OpenAI API.

### Context and citations

`KnowledgeContextBuilder` converts `RetrievalHit` rows into `S1…Sn` documents
with article_id, version_id, title, and truncated content. It does not query
the database and does not read chunk metadata for ACL.

Citations are application-owned identities of **supplied** hits, not LLM
inventions. Unknown `[S99]` ids are dropped.

Retrieved KB text and the user question are untrusted DATA. Prompt injection
inside either cannot switch tenant or grant ACL.

### No-answer

No production `min_score`. If retrieval returns no authorized hits, the
service returns a structured no-answer **without** calling the LLM. If the
LLM replies `NO_ANSWER`, the service returns the same structured no-answer.

### Explicitly not in AI-9A

AI-9A shipped the internal service only. HTTP chat was added later (AI-9B).
Telegram AI, conversation persistence, and a second ACL layer were not
part of AI-9A.

## Public HTTP chat (AI-9B)

`POST /api/v1/ai/chat` exists. The endpoint is stateless. Tenant comes from
authenticated context. The request cannot select tenant: the body is only
`message` (`extra=forbid`). No `company_id`, `employee_id`, `actor_role`,
or `user_id` is accepted from the client.

### Flow

```
HTTP POST /api/v1/ai/chat
→ existing JWT auth (EmployeeUser)
→ actor_company_id / actor_employee_id / actor_role from current_user
→ AIChatService.answer
→ KnowledgeRetriever (ArticleService.list_articles ACL)
→ RAG / LLM
→ { answer, no_answer, citations }
```

`AIChatService` is the application boundary. KnowledgeRetriever is the ACL
boundary. ArticleService remains the only KB ACL authority. The API layer
does not query vector tables, call OpenAI, build prompts, or implement ACL.

Public citations expose `source_id`, `title`, and `article_id` (the same id
as `GET /knowledge/articles/{id}`). They do not expose `version_id`,
`chunk_index`, embeddings, scores, tenant ids, or prompts.

No-answer is HTTP 200 with `no_answer=true` and empty citations — not 404.

Rate limiting reuses `is_rate_limited` per authenticated employee
(`AI_CHAT_RATE_LIMIT`, default 20/minute). It is not an authorization
mechanism. Tests disable it (`0`).

AI freeze (AI-9B):

- POST /api/v1/ai/chat exists
- endpoint is stateless
- conversation persistence is NOT implemented
- AIChatService is the application boundary
- KnowledgeRetriever is the ACL boundary
- ArticleService remains the only KB ACL authority
- tenant comes from authenticated context
- request cannot select tenant
- no production min_score
- AI-8 live OpenAI evaluation remains NOT MEASURED

Telegram AI is a separate thin client (AI-9C) of this HTTP API.

## Telegram AI client (AI-9C)

AI-9C = Telegram AI client implemented.

Telegram is a thin client of the existing stateless HTTP RAG API. It does
**not** redesign AI-9A or AI-9B. It does not add an ACL service, a vector
store, a migration, conversation persistence, streaming, or workers.

### Flow

```
Telegram
    -> authenticated backend identity
    -> /api/v1/ai/chat
    -> AIChatService
    -> KnowledgeRetriever
    -> ArticleService ACL
    -> LLM
    -> response
```

Identity is the existing Telegram → `POST /auth/bot/telegram` (service token)
→ employee JWT mapping. The chat body is only `message`. Telegram cannot
select `company_id`, `employee_id`, or `role`.

Router order (mandatory): `/start` → onboarding FSM → cabinet → AI last.
AI must never intercept onboarding state messages, `/start`, or cabinet
commands.

- Telegram is NOT an ACL layer.
- Telegram does NOT access pgvector directly.
- Telegram does NOT call OpenAI directly.
- ArticleService remains the only KB authorization authority.
- KnowledgeRetriever remains the retrieval ACL boundary.
- AI HTTP API remains stateless.
- No conversation persistence.
- No new vector DB.
- No new migration.
- No production min_score change.
- No top_k change.

AI freeze (AI-9C):

- AI-9C Telegram AI client implemented
- Telegram handlers call POST /api/v1/ai/chat only
- Telegram is NOT an ACL layer
- Telegram does NOT access pgvector directly
- Telegram does NOT call OpenAI directly
- ArticleService remains the only KB ACL authority
- KnowledgeRetriever is the ACL boundary
- AIChatService is the application boundary
- tenant comes from authenticated context
- request cannot select tenant
- conversation persistence is NOT implemented
- no production min_score
- no top_k change
- AI-8 live OpenAI evaluation remains NOT MEASURED

## Out of scope until later AI stages

AI-9C delivered the Telegram thin client of `POST /api/v1/ai/chat`.

## Production hardening (AI-10A)

AI-10A = production hardening of the existing pipeline. It does **not** add
an AI product, conversation persistence, streaming, workers, a second ACL,
a new vector DB, ANN/HNSW, or a production `min_score`.

### Timeout model

| Boundary | Default | Notes |
|---|---|---|
| Embedding HTTP | `AI_EMBEDDING_TIMEOUT_SECONDS=30` | existing; indexing and retrieve |
| LLM HTTP | `AI_LLM_TIMEOUT_SECONDS=30` | existing |
| Internal RAG chat | `AI_CHAT_TIMEOUT_SECONDS=25` | cancels retrieve+LLM; HTTP 503 |
| Telegram HTTP client | 30s | unchanged; onboarding uses the same client |
| Health/ready | no OpenAI call | configuration check only |

Telegram 30s > chat 25s, so the bot receives a bounded 503 rather than hanging.

### Retry model

Centralized in `post_openai_json` (used by embedding and LLM providers).

- `AI_PROVIDER_MAX_RETRIES=2` extra attempts after the first (3 total max)
- backoff 0.2s then 0.4s, cap `AI_PROVIDER_RETRY_MAX_BACKOFF_SECONDS=2`
- 429 honors `Retry-After` only when it is an integer, capped at 2s
- retry: timeout, network, 429, 500, 502, 503, 504
- never retry: 401, 403, other 4xx, invalid JSON, invalid schema, validation

### Error classification

OpenAI failures map to existing AppErrors:

- credentials (401/403) → `ValidationError` (HTTP 400)
- timeout / network / 429 / 5xx / invalid JSON → `ServiceUnavailableError` (HTTP 503)
- forbidden Super Admin → `ForbiddenError` (HTTP 403)

Safe `error_class` values for logs/metrics: `timeout`, `network`, `rate_limit`,
`server_error`, `credentials`, `invalid_json`, `invalid_schema`, `unknown`.
Never the raw OpenAI body.

### Request correlation

Opaque `X-Request-ID` (UUID). Middleware binds a contextvar for:

HTTP → AIChatService → KnowledgeRetriever → LLM → OpenAI

The id is not employee id, company id, JWT, or the question. Telegram may log
it on API errors and must not show it to the user.

### Safe logging

Namespaces remain `app.kb.retrieve`, `app.kb.embed`, `app.kb.llm`, `app.kb.chat`.

Logged: request_id, operation, provider, model, actor_role, company_id,
employee_id, hit_count, citation_count, duration_ms, result, error_class,
retry_count, status.

Never logged: query, answer, prompt, KB body, embeddings, API key,
Authorization, JWT, invite token.

### Metrics

In-process counters only. No Prometheus dependency. Labels are bounded
(`provider`, `operation`, `result`, `error_class`). Not message, title, or
tenant strings.

### Rate limit

Unchanged: `AI_CHAT_RATE_LIMIT=20` / 60s per authenticated employee, before
OpenAI. Redis INCR+EXPIRE is atomic (Lua). Not authorization. No
cross-tenant bucket.

### Health

`/health` is liveness. `/ready` checks Postgres, Redis in production, and
whether hosted AI keys are configured. It never embeds, never prompts, never
calls OpenAI or Telegram.

### Statelessness

No conversation persistence. No shared prompt/response cache. Evaluation
`.ai7_embedding_cache` is not read by production chat, HTTP, or Telegram.

AI freeze (AI-10A):

- timeout model is bounded
- retries are bounded
- request correlation is opaque
- ArticleService remains the only KB ACL authority
- KnowledgeRetriever is the ACL boundary
- Telegram remains a thin HTTP client
- no production min_score
- no top_k change
- conversation persistence is NOT implemented
- AI-8 live OpenAI evaluation remains NOT MEASURED
- AI-11 is NOT started

## Conversation persistence foundation (AI-11A)

AI-11A = conversation persistence foundation. It stores employee-owned
threads and messages. It does **not** add conversational memory to the LLM,
conversation HTTP API, Telegram history, frontend chat UI, title generation,
streaming, WebSockets, or workers.

### Resource model

- `AIConversation` belongs to **one company and one employee**
  (`conversation.company_id == employee.company_id`).
- `AIMessage` belongs to a conversation (`role` is `user` or `assistant`).
- Status is `active` or `archived`. Archived threads stay readable and reject
  new messages. There is no public delete API.
- Title is nullable. AI-11A does not call an LLM to generate titles.

Conversation storage is **DATA**. It is not ACL authority.

```
ArticleService          → KB permissions
KnowledgeRetriever      → retrieval ACL boundary
ConversationService     → employee-owned thread storage only
```

Conversation rows cannot grant KB access, switch tenant, change employee,
change article visibility, change program assignment, or bypass
`ArticleService`. HR KB access is not HR conversation access. Admin and
Super Admin are not granted employee chat access by this service.

### Ownership

Actor identity is `actor_company_id` + `actor_employee_id` (JWT /
authenticated Telegram identity later). Client-supplied `company_id`,
`employee_id`, or `tenant_id` is never authority. `conversation_id` and
`message_id` are identifiers only. Reads and writes require:

```
conversation.id = requested_id
AND conversation.company_id = actor_company_id
AND conversation.employee_id = actor_employee_id
```

UUID probing of another employee's or company's thread is `NotFoundError`.

### RAG remains stateless

```
question → retriever → context → LLM → answer
```

Conversation history is **not** supplied to the LLM in AI-11A.
`POST /api/v1/ai/chat` remains unchanged in this stage (body is only
`message`). Telegram remains a thin stateless HTTP client. `AIChatService`
does not read or write conversations yet.

### Privacy

Message `content` is stored in PostgreSQL (the point of AI-11A) and must
never appear in application logs, exception messages, metrics, Redis keys,
or request ids. Logs may include `conversation_id`, `company_id`,
`employee_id`, `message_id`, `role`, result, and duration.

### RLS

`ai_conversations` already has tenant FORCE RLS. `ai_messages` denormalizes
`company_id` (same child-table pattern as `progress` / chunks) and uses the
same `tenant_isolation` policy. Employee-scoped privacy is enforced in
`ConversationService` on top of tenant RLS.

AI freeze (AI-11A):

- conversations are employee-owned
- company ownership is enforced
- messages belong to conversations
- conversation storage is not KB authorization
- ArticleService remains KB ACL authority
- KnowledgeRetriever remains retrieval ACL boundary
- conversation history is not yet supplied to LLM
- no conversation HTTP API
- no Telegram conversation history
- no title generation
- no streaming
- no WebSocket
- no worker
- no AI-11B

## Conversation-aware RAG (AI-11B)

AI-11B = conversation-aware RAG on `POST /api/v1/ai/chat`. It does **not**
add Telegram conversation persistence, a conversation HTTP CRUD API,
frontend chat UI, title generation, streaming, WebSockets, workers, query
rewriting, or a production `min_score`.

### Flow

```
AUTHENTICATED USER
        │
        ▼
POST /api/v1/ai/chat  { message, conversation_id? }
        │
        ▼
AIChatService
 /                    \
▼                      ▼
ConversationService    KnowledgeRetriever
        │                      │
        │                      ▼
        │               ArticleService
        │                      │
        │                      ▼
        │                 KB Context
        └──────────┬───────────┘
                   ▼
              LLMProvider
                   │
                   ▼
         ConversationService.complete_turn
                   │
          user message + assistant message
```

`ConversationService` owns conversation persistence and employee/company
ownership. `ArticleService` remains the only KB ACL authority.
`KnowledgeRetriever` remains the retrieval ACL boundary.

### Request / response

Body: `message` (required, ≤2000) and optional `conversation_id` (UUID).
`extra=forbid`. The client cannot send `company_id`, `employee_id`,
`tenant_id`, `user_id`, `actor_role`, `model`, `provider`, `top_k`, or
`min_score`.

Response: `{ answer, no_answer, conversation_id, citations }`. Citations
still expose only `source_id`, `title`, `article_id`.

If `conversation_id` is omitted, a new active conversation is created
**after** retrieval/LLM succeed, in the same commit as the first turn.
If provided, ownership is checked via ConversationService
(`id + company_id + employee_id`). Foreign or unknown ids are
`NotFoundError` (HTTP 404). Archived conversations reject new messages
(`ValidationError`).

### History is not knowledge

Conversation history is bounded prompt context only:

- at most `MAX_CHAT_HISTORY_MESSAGES` (10) newest whole messages
- at most `MAX_CHAT_HISTORY_CHARS` (12000)
- chronological after a newest-first load
- never embedded, never retrieved, never used as ACL
- never assigned `[S1]` citation ids
- current question is always sent separately and always retrieved

Every new question performs a **new** KnowledgeRetriever call with the
current question text. History is not a KB source and cannot bypass
ArticleService.

The LLM user prompt separates:

1. `<conversation_history>` (untrusted DATA)
2. `<current_question>` (untrusted DATA)
3. `<knowledge_context>` with `<source id="Sn">` only

### Persistence

Database transactions are **not** held during OpenAI/LLM network calls.

After a successful retrieve+LLM (or structured no-answer):

one `complete_turn` commit writes user message + assistant message +
`conversation.updated_at`. LLM 503/timeout persists nothing. No assistant
error role. Empty conversations are not created when the LLM fails.

No-answer turns persist the user question and the existing
`NO_ANSWER_MESSAGE` assistant text so follow-ups keep a thread.

### Telegram

Telegram remains a thin stateless HTTP client until AI-11C. It still sends
only `{ "message": "..." }` and ignores `conversation_id` in the response.

AI freeze (AI-11B):

- conversation-aware RAG
- ConversationService owns conversation persistence
- ArticleService remains KB ACL authority
- KnowledgeRetriever remains retrieval ACL boundary
- conversation history is not KB authority
- history is not used for ACL
- history is not a citation source
- every new question performs retrieval
- conversation history is bounded
- Telegram remains stateless until AI-11C
- no streaming
- no WebSockets
- no workers
- no new vector DB
- no min_score calibration
- no query rewriting
- no AI-11C

## Telegram conversation persistence (AI-11C)

AI-11C = ephemeral Telegram session pointer for conversation-aware RAG.
It does **not** add a conversation HTTP CRUD API, frontend chat UI, title
generation, streaming, WebSockets, workers, query rewriting, or a
production `min_score`.

### Flow

```
Telegram user
        │
        ▼
Redis pointer  bot:ai:conversation:{telegram_user_id}
        │
        ▼
POST /api/v1/ai/chat  { message, conversation_id? }
        │
        ▼
AIChatService (authorization + RAG + persistence)
```

Telegram maintains an **ephemeral current conversation pointer** in Redis.
PostgreSQL remains the source of truth for conversations and messages.
Redis is only the Telegram session pointer. Telegram never authorizes
conversations. The HTTP API remains the authorization boundary.
`ArticleService` remains KB ACL authority. `KnowledgeRetriever` remains
the retrieval ACL boundary. Telegram never calls OpenAI and never accesses
vectors. No conversation schema changes. No new migration.

`/newchat` clears the Redis pointer only. It does not archive or delete
Postgres rows. A missing Redis pointer starts a new conversation.

Stale pointer (HTTP 404) or archived thread (HTTP 400 with the existing
archived-conversation contract) is recovered **once**: clear pointer, retry
without `conversation_id`, store the new id.

### Identity

The Redis key uses the stable Telegram user id already used for bot JWT
cache. Ownership is still the employee JWT. Telegram cannot send
`company_id`, `employee_id`, `role`, `tenant_id`, `model`, `provider`,
`top_k`, or `min_score`.

AI freeze (AI-11C):

- Telegram maintains ephemeral current conversation pointer
- PostgreSQL remains source of truth for conversations/messages
- Redis is only the Telegram session pointer
- Telegram never authorizes conversations
- HTTP API remains authorization boundary
- ArticleService remains KB ACL authority
- KnowledgeRetriever remains retrieval ACL boundary
- Telegram never calls OpenAI
- Telegram never accesses vectors
- no conversation schema changes
- no new migration
- no streaming
- no workers
- no frontend
- no CRUD conversation API
- no AI-12

## Employee frontend AI chat (AI-12A)

AI-12A = Employee Workspace chat UI over the existing
`POST /api/v1/ai/chat` contract. The frontend is an authenticated HTTP
client only. It does **not** add conversation HTTP CRUD, history restore
after refresh, streaming, WebSockets, SSE, workers, Prometheus, ANN,
query rewriting, or a production `min_score`.

### Route

`/employee/ai` inside `EmployeeLayout`, gated by the existing employee
workspace + `RequireRole(['employee'])`. Navigation label: AI Ассистент.
HR / Company Admin / Platform Admin do not get a separate AI UI in this
stage.

### HTTP client

`frontend/src/services/aiApi.ts` `postAIChat(message, conversationId?)`
calls `apiRequest` (cookie session + refresh). Body is only:

```
{ "message": "..." }
{ "message": "...", "conversation_id": "<uuid from previous response>" }
```

The client never sends `company_id`, `employee_id`, `tenant_id`,
`user_id`, `actor_role`, `model`, `provider`, `top_k`, or `min_score`.
`conversation_id` is a continuation token only. Ownership remains
backend (`ConversationService` + JWT). Frontend is never an authorization boundary.

First message omits `conversation_id`. Follow-ups send the id returned
by the server. New Chat clears React state only (no DELETE, no archive).
Browser refresh drops local messages (no GET conversation API).

### Rendering

Assistant text is untrusted React text (`whitespace-pre-wrap`). No
`dangerouslySetInnerHTML`. Citations show **titles** only and link to
the existing employee article route `/employee/knowledge/:articleId`.
Internal `source_id`, scores, embeddings, tenant ids, and model names
are not displayed. Empty citations are hidden. `no_answer` is a normal
assistant message.

### Invariants

- ArticleService remains the only KB ACL authority
- KnowledgeRetriever remains the retrieval ACL boundary
- AIChatService remains the orchestration layer
- ConversationService remains conversation ownership authority
- Telegram remains unchanged
- AI-8 live OpenAI evaluation remains NOT MEASURED
- no conversation HTTP CRUD API
- no streaming
- no WebSockets
- no SSE
- no workers
- no Prometheus
- no ANN
- no min_score
- no retrieval redesign
- no AI-12B

## Employee conversation history (AI-12B)

AI-12B = HTTP conversation history for the Employee Workspace chat UI.
It reuses `ai_conversations` / `ai_messages`. It does **not** add streaming,
WebSockets, SSE, workers, LLM titles, Telegram changes, or retrieval
redesign.

### Endpoints

Identity is always the authenticated session. Clients cannot send
`company_id`, `employee_id`, `tenant_id`, or `role`.

GET /api/v1/ai/conversations returns active owned threads (metadata only).
GET /api/v1/ai/conversations/{conversation_id} returns chronological messages.
DELETE /api/v1/ai/conversations/{conversation_id} archives the thread.

```
GET    /api/v1/ai/conversations
GET    /api/v1/ai/conversations/{conversation_id}
DELETE /api/v1/ai/conversations/{conversation_id}
POST   /api/v1/ai/chat   (unchanged request/response contract)
```

List returns metadata only (`conversation_id`, `title`, timestamps,
`last_message_preview`, `message_count`), ordered by `updated_at DESC`.
Detail returns chronological messages. Pagination uses existing
`offset`/`limit` (default 100, max 1000). The Employee UI does not paginate
in AI-12B.

### Ownership

```
conversation.id = requested_id
AND conversation.company_id = actor_company_id
AND conversation.employee_id = actor_employee_id
AND status = active
```

Unknown, foreign, or archived ids are `NotFoundError` (HTTP 404).
Frontend is never an authorization boundary.

### Archive is the delete convention

DELETE archives the thread (`status=archived`). Rows stay in PostgreSQL.
Archived conversations leave the history list, reject new messages, and
GET as 404. `/newchat` and the UI **Новый чат** button do not archive.

### Titles and citations

Title is the first user message, truncated, UTF-8 preserved. No LLM title
call. Assistant messages may store public citations
(`source_id`, `title`, `article_id`) and `no_answer`. Scores, embeddings,
and `version_id` are not stored.

### Frontend

`/employee/ai` loads the list, restores `?c=<conversation_id>` or the most
recently updated thread, and continues with `POST /ai/chat`. New Chat
clears local state only. Refresh uses the history API as source of truth
(URL `c` when present).

### Invariants

- ArticleService remains the only KB ACL authority
- KnowledgeRetriever remains the retrieval ACL boundary
- ConversationService remains conversation ownership authority
- Telegram remains unchanged
- AI-8 live OpenAI evaluation remains NOT MEASURED
- no streaming
- no WebSockets
- no SSE
- no workers
- no LLM-generated titles
- no AI-13

## End-to-end RAG evaluation (AI-8)

AI-8 now also measures the existing Employee RAG path (`AIChatService` →
`KnowledgeRetriever` → `LLMProvider`) against a frozen synthetic dataset.
It does **not** change retrieval, embeddings, chunking, prompts, `top_k`,
`min_score`, Telegram, or conversation APIs.

### Purpose

Measure retrieval hit rate, answer/citation/groundedness scores, no-answer
behavior, end-to-end latency, and tenant isolation. Do not treat Fake
providers as production quality.

### Dataset

`tests/ai/evaluation/dataset.json` (answerable, unanswerable, ambiguous,
citation, security). Articles remain `app/services/ai/eval_corpus.py`.
No production data, secrets, or employee PII.

### Metrics

- Retrieval: article-level Recall@`top_k` (production `top_k=5`)
- Answer / groundedness / citation: 0 incorrect, 1 partial, 2 correct
- No-answer precision and recall
- Latency min / P50 / P95 / max (sample is small; P95 is not statistically
  meaningful)
- Security: foreign `conversation_id`, cross-tenant continuation, Company B
  knowledge leak

### Execution

```
python -m scripts.evaluate_rag --write-report
```

Live OpenAI (never required for pytest/CI):

```
ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_rag --live-openai --write-report
```

Requires `AI_EMBEDDING_API_KEY`/`AI_LLM_API_KEY` or `OPENAI_API_KEY`.
Application startup does not import or run evaluation.

### Limitations

Small evaluation sample; results are directional and not statistically
representative. FakeLLM is a citation stub, not gpt-4o-mini quality.
does not change retrieval.

Latest measured result: `docs/ai/ai8-rag-evaluation.md`.
AI-8 live OpenAI evaluation remains NOT MEASURED unless that document
labels Live OpenAI embeddings+LLM as MEASURED.

## Out of scope until later AI stages

AI-12B delivered conversation history HTTP + Employee UI restore. Still
out of scope:

- public retrieval HTTP API (`/ai/search`)
- conversation history as a KB source
- LLM title generation
- query rewriting
- production relevance threshold / `min_score`
- changes to existing KB ACL
- credentials in the repository
- background index workers (Celery / Redis queue)
- Azure / local E5 / BGE providers
- ANN / HNSW index
- streaming / WebSockets / SSE
- HR / Admin AI UI
- AI-13
- AI-14
- AI-15
