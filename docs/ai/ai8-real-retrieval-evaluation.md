# AI-8 Real Retrieval Evaluation

Evaluation only. Production `min_score` remains unset. Production
`top_k` remains 5. No LLM, no chat API, no Telegram AI.

Labels:

- **MEASURED** — numbers produced by an actual evaluation run
- **NOT MEASURED** — the live OpenAI path was not executed; do not
  invent or copy FakeEmbeddingProvider scores as OpenAI quality

- Generated: `2026-08-16`
- FakeEmbeddingProvider: **MEASURED** (`fake`)
- OpenAI `text-embedding-3-small`: **NOT MEASURED**

## Dataset

Synthetic corpus in `app/services/ai/eval_corpus.py`. No production
employee PII, no live tenant data, no secrets.

- number of cases: 42
- answerable: 34
- no-answer cases: 8
- RU: 15
- KK: 10
- EN: 17
- cross-language (answerable): 9
- exact-identity: 3
- paraphrase (answerable): 31

## Model

- Fake provider: in-process SHA-256 hash embeddings (not semantic)
- OpenAI model: `text-embedding-3-small`

## Dimensions

- pgvector column / evaluation width: `1536`
- OpenAI native width: `1536`

## Evaluation methodology

1. Seed Company A + Company B articles through `ArticleService`
   (publish → post-commit index). Company B holds a unique bonus
   article that must never appear in Company A hits.
2. Query the production `KnowledgeRetriever` as a Company A employee.
3. Authorization path is unchanged:
   AUTH → TENANT → EMPLOYEE → PUBLISHED → VISIBILITY → PROGRAM ACL
   → RETRIEVAL.
4. Article-level hit: an acceptable `article_id` appears in top-k.
5. CI / pytest uses FakeEmbeddingProvider or a mocked HTTP client.
   Live OpenAI requires `ONBOARDAI_AI7_LIVE_OPENAI=1` and
   `--live-openai` plus `AI_EMBEDDING_API_KEY` or `OPENAI_API_KEY`.
6. Embeddings are batched and cached under `.ai7_embedding_cache/`
   (gitignored, model-specific JSON, hash keys only, no API keys,
   no raw query text, `not_a_kb_index=true`).

## Fake results

**MEASURED** against FakeEmbeddingProvider. Hash embeddings are not
semantic — do not use these scores to choose production thresholds
or to claim RU/KK/EN quality.

- Recall@1: 0.176 (6/34, misses=28)
- Recall@3: 0.294 (10/34, misses=24)
- Recall@5: 0.471 (16/34, misses=18)
- Recall@10: 0.676 (23/34, misses=11)
- exact-identity Recall@5: 1.000 (3/3, misses=0)
- paraphrase Recall@5: 0.419 (13/31, misses=18)
- foreign-tenant leaks: 0

## OpenAI results

**NOT MEASURED.** Live `text-embedding-3-small` evaluation was
not executed in this document generation. Run:

```
ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_kb_retrieval --live-openai --write-report
```

## Recall@K

| k | Fake (MEASURED) | OpenAI |
|---:|---|---|
| 1 | 0.176 (6/34, misses=28) | NOT MEASURED |
| 3 | 0.294 (10/34, misses=24) | NOT MEASURED |
| 5 | 0.471 (16/34, misses=18) | NOT MEASURED |
| 10 | 0.676 (23/34, misses=11) | NOT MEASURED |

## Score distributions

OpenAI score distributions: **NOT MEASURED**.

Fake (MEASURED, not semantic):
- true positives: n=16 min=0.009 max=1.000 mean=0.213 median=0.032
- false positives (wrong top-1 or no-answer hits): n=36 min=0.022 max=0.081 mean=0.049 median=0.049
- misses: n=18 min=0.022 max=0.081 mean=0.048 median=0.047
- no-answer: n=8 min=0.030 max=0.068 mean=0.048 median=0.047

## Threshold analysis

OpenAI thresholds: **NOT MEASURED**. Fake thresholds below are
shown for pipeline completeness only — do not pick a production
`min_score` from hash embeddings.

| threshold | TP | FP | FN | TN | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.20 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.25 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.30 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.35 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.40 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.45 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.50 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.55 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.60 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.65 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.70 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.75 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.80 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.85 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |
| 0.90 | 3 | 0 | 31 | 8 | 1.000 | 0.088 | 0.162 |

**Recommendation (Fake):** Keep production `min_score` unset. Answerable-hit and no-answer score distributions overlap on this corpus, so a cutoff would trade recall for incomplete no-answer rejection.

## Multilingual analysis

OpenAI RU/KK/EN and cross-language quality: **NOT MEASURED**.
Do not claim multilingual quality from FakeEmbeddingProvider.

Fake query-language Recall@5 (MEASURED, not semantic):

- RU Recall@5: 0.417 (5/12, misses=7)
- KK Recall@5: 0.444 (4/9, misses=5)
- EN Recall@5: 0.538 (7/13, misses=6)
- same-language Recall@5: 0.480 (12/25, misses=13)
- cross-language Recall@5: 0.444 (4/9, misses=5)
- ru→en Recall@5: 1.000 (1/1, misses=0)
- en→ru Recall@5: 0.500 (1/2, misses=1)
- kk→ru Recall@5: 0.000 (0/2, misses=2)
- ru→kk Recall@5: 0.000 (0/1, misses=1)
- en→kk Recall@5: 0.000 (0/1, misses=1)
- kk→en Recall@5: 1.000 (2/2, misses=0)

## No-answer analysis

OpenAI no-answer behavior: **NOT MEASURED**.

- Fake NO_ANSWER_CASES: 8
- Fake no-answer cases that still returned hits: 8

## Chunking observations

- wifi-en: {'chunk_count': 1, 'title_prefix': True}
- onboarding-en: {'chunk_count': 1, 'title_prefix': True}
- conduct-ru: {'chunk_count': 2, 'title_prefix': True}
- meetings-en: {'chunk_count': 1, 'title_prefix': True}
- html-ru: {'chunk_count': 1, 'title_prefix': True}
- kk-bullets: {'chunk_count': 1, 'title_prefix': True}
- failures: []
- overlap_chars: 200
- passed: True

The character-window chunker was not redesigned in AI-8.
Concrete OpenAI misses (if any) are listed below; a chunking
change requires evidence that a window split hid the answer.

### Answerable misses (article not in top-5)

OpenAI misses: **NOT MEASURED**.

Fake misses (MEASURED, not semantic):
- `ru-sick` lang=ru cross=False expected=['sick-ru'] top=equipment-en score=0.038
- `ru-expenses` lang=ru cross=False expected=['expenses-ru'] top=conduct-ru score=0.033
- `ru-fire` lang=ru cross=False expected=['fire-ru'] top=conduct-ru score=0.022
- `ru-payroll` lang=ru cross=False expected=['payroll-ru'] top=leave-kk score=0.068
- `ru-vpn-office` lang=ru cross=False expected=['vpn-en', 'vpn-ru'] top=sick-ru score=0.064
- `kk-hours` lang=kk cross=False expected=['hours-kk'] top=nda-en score=0.049
- `kk-probation` lang=kk cross=False expected=['probation-kk'] top=payroll-ru score=0.029
- `kk-badge` lang=kk cross=False expected=['badge-kk'] top=vpn-ru score=0.040
- `en-wifi` lang=en cross=False expected=['wifi-en'] top=conduct-ru score=0.063
- `en-equipment` lang=en cross=False expected=['equipment-en'] top=leave-en score=0.033
- `en-remote` lang=en cross=False expected=['remote-en'] top=probation-kk score=0.045
- `cross-kk-ru-leave` lang=kk cross=True expected=['leave-ru', 'leave-kk', 'leave-en'] top=vpn-en score=0.054
- `cross-ru-kk-hours` lang=ru cross=True expected=['hours-kk'] top=conduct-ru score=0.057
- `cross-en-kk-probation` lang=en cross=True expected=['probation-kk'] top=remote-en score=0.051
- `cross-en-ru-fire` lang=en cross=True expected=['fire-ru'] top=meetings-en score=0.081
- `cross-kk-ru-sick` lang=kk cross=True expected=['sick-ru'] top=hours-kk score=0.046
- `en-helpdesk-sla` lang=en cross=False expected=['helpdesk-en'] top=leave-kk score=0.040
- `ru-expenses-per-diem` lang=ru cross=False expected=['expenses-ru'] top=leave-en score=0.052

## Security results

- Fake foreign-tenant article leaks: 0
- OpenAI foreign-tenant article leaks: NOT MEASURED

ACL tests (pytest, FakeEmbeddingProvider) continue to prove:

- Company A cannot retrieve Company B
- UUID probing cannot expose B
- B's exact text cannot retrieve B through A
- metadata poisoning does not bypass ACL
- historical / draft / archived versions are not retrieved
- program visibility still respects assignment
- cancelled assignments remain inaccessible
- Super Admin remains forbidden without tenant impersonation

`ArticleService` remains the only KB authorization authority.

## Cost / operational observations

**NOT MEASURED** for live OpenAI. Fake evaluation does not
call the network.

- Fake cache hits: 3
- Fake network batches (in-process provider): 60

## Recommendation for top_k

OpenAI top-k recommendation: **NOT MEASURED**. Fake top-k is
not a production signal.

Fake (not for production): Recall@1=0.176, Recall@3=0.294, Recall@5=0.471, Recall@10=0.676. Recall@5 materially improves on Recall@3. Recall@10 is higher than Recall@5. Inspect remaining misses before raising production `top_k`. Production default remains 5. This stage does not change the production default.

Production default `top_k=5` is unchanged.

## Recommendation for min_score

OpenAI `min_score` recommendation: **NOT MEASURED**.
Do not choose a production threshold from FakeEmbeddingProvider.

Fake (not for production): Keep production `min_score` unset. Answerable-hit and no-answer score distributions overlap on this corpus, so a cutoff would trade recall for incomplete no-answer rejection.

## Known limitations

- Dataset is synthetic and small (42 cases). Pair cells such as
  RU→EN may have n=1; treat pair recall as directional, not a
  population estimate.
- FakeEmbeddingProvider is a hash. Paraphrase and cross-language
  Fake Recall@K are not production quality.
- Live OpenAI is opt-in, cached, and never part of pytest/CI.
- Without `min_score`, no-answer queries still return neighbors.
- No LLM, no citations runtime, no `/ai/chat` or `/ai/search`.
- Evaluation tenants are created and deleted by the script; they
  are not production companies.

## Tests

See `tests/ai/test_eval_*.py`, `tests/ai/test_openai_embeddings.py`,
`tests/security/test_ai_retrieval_acl.py`, and
`tests/security/test_ai_eval_tenant_isolation.py`.

