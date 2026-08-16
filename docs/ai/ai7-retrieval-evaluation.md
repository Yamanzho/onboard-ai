# AI-7 Retrieval Evaluation

Evaluation only. Production `min_score` remains unset. No LLM, no chat
API, no Telegram AI. Numbers below are measured, not assumed.

- Provider: `fake`
- Live OpenAI: `False`

## Dataset
- number of cases: 42
- answerable: 34
- no-answer cases: 8
- RU: 15
- KK: 10
- EN: 17

## Recall
- Recall@1: 0.176 (6/34, misses=28)
- Recall@3: 0.294 (10/34, misses=24)
- Recall@5: 0.471 (16/34, misses=18)

## Top-K

- Recall@1: 0.176 (6/34, misses=28)
- Recall@3: 0.294 (10/34, misses=24)
- Recall@5: 0.471 (16/34, misses=18)
- Recall@10: 0.676 (23/34, misses=11)

Recall@5 minus Recall@3: +0.176.
Recall@5 improves over Recall@3.

## Score distribution
- all top scores: n=42 min=0.022 max=1.000 mean=0.117 median=0.050
- hits (answerable, article in top-5): n=16 min=0.028 max=1.000 mean=0.230 median=0.058
- misses (answerable, article not in top-5): n=18 min=0.022 max=0.081 mean=0.048 median=0.047
- no-answer: n=8 min=0.030 max=0.068 mean=0.048 median=0.047

## Threshold analysis

Predicted ANSWER iff top score ≥ candidate. Production threshold is
**not** enabled. No candidate is auto-selected.

| threshold | TP | FP | FN | TN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| 0.30 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.35 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.40 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.45 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.50 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.55 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.60 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.65 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.70 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.75 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.80 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.85 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |
| 0.90 | 3 | 0 | 31 | 8 | 1.000 | 0.088 |

## Language results

- RU Recall@5: 0.417 (5/12, misses=7)
- KK Recall@5: 0.444 (4/9, misses=5)
- EN Recall@5: 0.538 (7/13, misses=6)
- cross-language Recall@5: 0.444 (4/9, misses=5)

## Exact-phrase vs paraphrase (answerable)
- exact-phrase Recall@5: 1.000 (3/3, misses=0)
- paraphrase Recall@5: 0.419 (13/31, misses=18)

## Chunking results
- wifi-en: {'chunk_count': 1, 'title_prefix': True}
- onboarding-en: {'chunk_count': 1, 'title_prefix': True}
- conduct-ru: {'chunk_count': 2, 'title_prefix': True}
- meetings-en: {'chunk_count': 1, 'title_prefix': True}
- html-ru: {'chunk_count': 1, 'title_prefix': True}
- kk-bullets: {'chunk_count': 1, 'title_prefix': True}
- failures: []
- overlap_chars: 200
- passed: True

## No-answer results
- NO_ANSWER_CASES: 8
- no-answer cases that still returned retrieval hits: 8

Without a production `min_score`, the retriever returns the nearest
allowed chunks whenever the tenant corpus is non-empty. Hits on
no-answer questions are expected until a threshold is chosen in a
later stage.

## Misses (answerable, article not in top-5)

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

## Security verification
- foreign-tenant article leaks: 0

## Tests

See `tests/ai/test_eval_*.py` and
`tests/security/test_ai_eval_tenant_isolation.py`.

## Remaining weaknesses

- FakeEmbeddingProvider is a hash, not a semantic model. Paraphrase
  and cross-language Recall@K are not production quality.
- Without `min_score`, every no-answer query still returns nearest
  neighbors from the allowed tenant corpus.
- Hit vs miss vs no-answer scores overlap under fake embeddings;
  threshold candidates cannot be calibrated from this provider.
- Live OpenAI numbers require an explicit opt-in run and are not
  part of CI.

## Full regression

Measured 2026-08-16 against FakeEmbeddingProvider (CI default). Live OpenAI
was not run.

- pytest: 679 passed
- pytest -m security: 250 passed
- Alembic: one head `e1f2a3b4c5d6`
- frontend typecheck / lint / build: pass
- docker compose config: pass
- production compose config: pass
- production `top_k` default remains 5; production `min_score` remains unset
- no new Python dependencies

