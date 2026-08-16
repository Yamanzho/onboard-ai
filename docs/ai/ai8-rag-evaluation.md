# AI-8 Evaluation Report

End-to-end RAG evaluation of the existing `AIChatService` path.
This stage does **not** change retrieval, embeddings, prompts,
`top_k`, or `min_score`.

Labels:

- **MEASURED** — numbers produced by an actual evaluation run
- **NOT MEASURED** — that provider path was not executed

- Generated: `2026-08-16`
- Fake embeddings + FakeLLM: **MEASURED**
- Live OpenAI embeddings+LLM: **NOT MEASURED**
- Embedding provider: `fake`
- LLM provider: `fake` (`fake-llm`)
- Production top_k used: `5`

## Dataset

- cases: 28
- ambiguous: 4
- answerable: 14
- citation: 14
- security: 2
- unanswerable: 8

Corpus: synthetic articles in `app/services/ai/eval_corpus.py`.
Questions: `tests/ai/evaluation/dataset.json`.

## Retrieval

- Recall@5 / source hit rate: 0.444

Article-level hit: an expected source key appears in production
`top_k=5` retrieval hits. Exact chunk index is not required.

## Answer

correct=0, partial=10, incorrect=18, mean=0.357

## Groundedness

correct=0, partial=20, incorrect=8, mean=0.714

## Citation accuracy

correct=3, partial=15, incorrect=10, mean=0.750

## No-answer

- TP=0 FP=0 FN=8 TN=18
- Precision: n/a
- Recall: 0.000

## Latency

- n=28
- min: 49.1 ms
- P50 / median: 54.3 ms
- P95: 60.5 ms
- max: 63.6 ms

P95 is reported for completeness; the sample is too small for a
statistically meaningful tail estimate.

## Security

- overall: PASS
- same-tenant foreign conversation_id: PASS — peer employee received NotFoundError
- cross-tenant conversation_id: PASS — tenant B received NotFoundError
- unknown conversation_id: PASS — unknown conversation_id returned NotFoundError
- cross-tenant knowledge retrieval: PASS — Company B article ids absent from Company A hits

## Findings

- 8 unanswerable questions received an answer (false-negative no-answer). Without a production min_score, nearest-neighbor hits still reach the LLM.
- Recall@5 is 0.444 on this dataset. Fake hash embeddings are not a semantic quality signal.
- No case scored fully correct on required facts. FakeLLM is a citation stub; live OpenAI is required for factual-answer measurement.

## Limitations

- Small evaluation sample; results are directional and not statistically representative.
- P95 latency is not statistically meaningful at this sample size.
- FakeEmbeddingProvider is a hash, not a semantic embedding model.
- FakeLLMProvider emits a citation stub and is not a factual-answer quality signal for production gpt-4o-mini.
- Live OpenAI numbers appear only when that path actually ran.
- Production top_k remains 5; min_score remains unset.

## How to reproduce

```
python -m scripts.evaluate_rag --write-report
```

Live OpenAI (never required for pytest/CI):

```
ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_rag --live-openai --write-report
```

Requires `AI_EMBEDDING_API_KEY`/`AI_LLM_API_KEY` or `OPENAI_API_KEY`.
Do not commit keys. Application startup does not run this evaluation.

