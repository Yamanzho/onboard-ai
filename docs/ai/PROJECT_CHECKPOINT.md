# OnboardAI Project Checkpoint

## Date

2026-08-17

## Completed

### AI-12A
Employee AI Chat UI:
- /employee/ai
- chat
- citations
- errors
- loading
- New Chat
- employee-only UI

Status: COMPLETE

### AI-12B
Conversation History:
- conversation list
- conversation get
- archive
- persistent messages
- titles
- citations
- refresh restore
- desktop history
- mobile drawer
- employee + tenant ACL
- IDOR protection

Status: COMPLETE

### AI-8
RAG Evaluation:
- reproducible evaluation runner
- 28-case dataset
- answerable/unanswerable/ambiguous cases
- retrieval metrics
- answer scoring
- groundedness
- citation scoring
- no-answer evaluation
- latency
- security evaluation

Status: COMPLETE as measurement stage

Live OpenAI:

NOT MEASURED

## Current Metrics

pytest:
958 passed

security:
344 passed

typecheck:
PASS

lint:
PASS

build:
PASS

Alembic:
f3a4b5c6d7e8

## Important AI-8 Findings

These are **fake-provider / local** measurements. They are not production
OpenAI quality, not semantic retrieval quality, and not a live latency
baseline.

- Fake Recall@5 = 0.444
- FakeLLM answer mean = 0.357
- No-answer recall = 0.000
- Citation score mean = 0.750
- Fake latency P50 = 54.3 ms (latest local run; earlier run 48.4 ms)
- Fake latency P95 = 60.5 ms (latest local run; earlier run 84.3 ms)
- Security = PASS

Live OpenAI quality remains unknown.

## Known Limitations

1. Live OpenAI evaluation has not been executed.
2. Fake embeddings are not semantic embeddings.
3. FakeLLM does not represent real GPT answer quality.
4. No-answer behavior needs evaluation with real retrieval/LLM.
5. UI history does not paginate beyond the first 100 conversations.
6. AI-13 streaming is not implemented.

## Next Recommended Step

Run real OpenAI evaluation when quota-bearing credentials are available:

```
ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_rag --live-openai --write-report
```

Then analyze:

- retrieval quality
- answer correctness
- groundedness
- citation accuracy
- no-answer behavior
- latency

Do NOT optimize RAG before obtaining the live baseline unless a critical
production bug is discovered.

Potential next stages after live evaluation:

1. RAG optimization
2. no-answer threshold analysis
3. retrieval improvements
4. AI-13 streaming

Do not automatically start AI-13.
