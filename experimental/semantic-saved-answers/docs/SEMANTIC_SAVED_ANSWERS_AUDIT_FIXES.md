# Semantic Saved Answers — Audit Fix Review

**Branch:** `feat/semantic-saved-answers` (local only; not pushed)  
**Paid API calls:** 0  
**Production database:** not modified  
**Production readiness:** not ready to deploy

## 1. Fixes

### Unsafe Stage 0 matching

Canonical text no longer folds `is`/`was`/`did`/`does` into one token. Rule reuse also requires the same copula. Exact repeats stay a single indexed lookup.

"Who is the president of France?" and "Who was the president of France?" do not reuse each other. Same-tense wording such as "Who was Neil Armstrong?" and "Who was Neil Armstrong really?" still matches in Stage 0. A tense change can still be approved later by the verifier, and only when the stored answer and citations satisfy the new question.

### Evidence-aware verifier

The verifier receives the complete saved answer and every stored citation, inside an `<untrusted>` fence. Instructions tell the model to ignore commands inside that fence. Reuse requires all of: equivalent question, answer satisfies unchanged, citations support it, nothing requested is omitted, and high confidence.

If the answer is longer than 6,000 characters, there are more than 8 citations, an excerpt is longer than 1,500 characters, a positive answer has no citations, or any citation is malformed, the verifier is not called and full RAG runs.

### Match policy

`current_match_policy_version(model)` is a hash of the verifier model, prompt, JSON schema, bounds, and Voyage `voyage-4-large` / 1,024-dimension query setup. Semantic lookup requires that exact value. Rows from another policy, and rows with a null embedding, stay available for exact and same-tense rule reuse only. They are not paraphrased automatically. The next full answer for a new wording stores a fresh embedding under the current policy. The old answer text is not rewritten. No paid backfill is included.

### Usage accounting

Each request records separate lines for the Voyage query embedding, every equivalence attempt, Voyage rerank, and `gpt-6.1-sol` answer generation. A known total replaces the $0.05 reservation, so a cheap semantic hit no longer keeps a $0.05 daily-budget hold. A timeout or dropped connection with no token count keeps one $0.05 hold per such attempt, added to the known lines, and is marked `uncertain`. A definite 4xx rejection is treated as unbilled and the unused hold is released. Daily question, per-minute, and dollar limits still run before any model call.

`gpt-6-luna` has no price in this repository. Verification lines use the published `gpt-6.1-sol` rates ($2 / $10 per million tokens) so the daily cap cannot be under-counted. That is a protective estimate, not an invoice.

## 2. Files

| File | Why |
|---|---|
| `cloud_backend/bookrag_cloud/question_match.py` | Preserve tense; block cross-tense rule reuse |
| `cloud_backend/bookrag_cloud/equivalence.py` | Evidence bounds, injection fence, hashed policy, stricter decision |
| `cloud_backend/bookrag_cloud/offline_equivalence.py` | Offline oracle matches the new decision fields |
| `cloud_backend/bookrag_cloud/usage_cost.py` | Per-call estimates and reservation settlement |
| `cloud_backend/bookrag_cloud/providers.py` | Full evidence prompt; timeout versus rejected call |
| `cloud_backend/bookrag_cloud/repository.py` | Policy filter; known cost replaces the hold |
| `cloud_backend/bookrag_cloud/main.py` | Wire evidence, policy, and the cost ledger |
| `cloud_backend/bookrag_cloud/schemas.py` | `usage.components` and `usage.cost_certainty` |
| `cloud_backend/migrations/005_saved_answer_question_embeddings.sql` | Comment: null embeddings are not semantic candidates |
| `cloud_backend/migrations/006_usage_cost_breakdown.sql` | `cost_breakdown`, `cost_certainty` |
| `cloud_backend/API_CONTRACT_v1.md`, `API_OPENAPI_v1.json` | Contract matches the new usage fields |
| `cloud_backend/tests/test_question_match.py` | Tense, date, ordinal, quantity, entity, negation, intent |
| `cloud_backend/tests/test_equivalence.py` | Evidence bounds, fence, policy hash |
| `cloud_backend/tests/test_audit_regressions.py` | Long answers, citations, refusals, multi-candidate cost, bad JSON, timeout, policy, concurrency, isolation |
| `cloud_backend/tests/test_saved_answers.py`, `test_api.py`, `test_mocked_cloud_flow.py`, `test_semantic_saved_answers.py` | Fakes accept the new arguments |
| `cloud_backend/benchmarks/build_verifier_eval_set.py` | 60 dev + 240 held-out labeled pairs |
| `cloud_backend/benchmarks/verifier_eval_set.json` | The labeled set. `model_scored` is false |
| `cloud_backend/benchmarks/verifier_eval_plan.py`, `verifier_eval_budget.json` | Budget. Live mode refuses to run |
| `cloud_backend/tests/test_eval_set_and_migrations.py` | Split checks and optional isolated migration apply |

The frontend was not changed. It already shows "Previously answered" when `reused_answer` is true and ignores the new usage fields.

## 3. Test results

All provider behavior below is simulated. No Voyage or OpenAI call was made.

| Suite | Result |
|---|---|
| Backend pytest | **92 passed, 1 skipped** |
| Frontend vitest | **50 passed** |
| Frontend `tsc --noEmit` | passed |
| Frontend `next build` | passed |
| Offline matcher, n=18 | Rules: precision 1.0, recall 0.333, false reuse **0**. Semantic offline oracle: precision 1.0, recall 1.0, false reuse **0**, hard-negative false reuse **0** / 12 |

Rule recall fell from 0.50 to 0.333 because "is" versus "was" is no longer an automatic match. That is the intended correctness change. The offline oracle is not a live model result.

The skipped test is the optional apply against `BOOKRAG_ISOLATED_DATABASE_URL`. It was not set. A separate empty local database was used instead; see section 5.

## 4. Remaining risks

- Live `gpt-6-luna` and `gpt-6.1-sol` have not been scored. Offline passes do not prove they will reject every hard negative.
- Same-tense rule reuse still happens without a verifier. "Who was Neil Armstrong?" matches "Who was Neil Armstrong really?". A same-tense change that still alters the fact, and that the rules do not see, can be reused. The verifier path does not review Stage 0 hits.
- The per-document lock is held during verification and retrieval.
- An uncertain call with no token report adds $0.05 even if the provider did not bill it. The daily cap is then stricter than the true invoice.
- Luna's real price may be lower than the Sol stand-in. The ledger will overstate those lines until a published rate is added.
- Saved rows from before this policy have `match_policy_version = rules-v1` and usually no embedding. Paraphrases of those rows run full RAG.
- The answer lock can still make a second question on the same PDF wait while a verifier call is in flight.

## 5. Migration validation

No production backup is in this workspace, and no production host was contacted.

On local PostgreSQL 16 (`/tmp:5432`), a new empty database `bookrag_semantic_migration_scratch` was created with stub `auth.users`, `auth.uid()`, and `storage.buckets` so the Supabase-shaped scripts could run. `vector` and `pgcrypto` were already available. Migrations `001` through `006` applied in order. `saved_answers` gained `question_embedding vector(1024)` and `match_policy_version`. `usage_events` gained `cost_breakdown jsonb` and `cost_certainty`. The scratch database was then dropped.

This proves the SQL applies to an empty compatible database. It does not prove it applies cleanly to the production data set.

## 6. Real-model evaluation plan

**Not run.** `--live` exits with a refusal.

| Item | Value |
|---|---|
| Dev pairs | 60 |
| Held-out pairs | 240, no shared question text with dev |
| Models | `gpt-6-luna` and `gpt-6.1-sol`, same pairs |
| Calls if approved | 600 verifier calls |
| Assumed tokens | 900 input and 80 output per call |
| Rate used for the ceiling | Sol Standard, $2 / $10 per million, for both models |
| Estimate before retries | **$1.56** |
| Estimate with 20% retry allowance | **$1.87** |
| Requested hard cap | **$5.00** |

Measures: false reuse, precision, recall, latency, tokens, and estimated dollars. Score dev first. Do not tune the prompt on the held-out split. A simulated verifier result is not a success claim.

Approval is required before any of those calls.

## 7. Verdict

The professor's failure mode in the audit — treating "who is" and "who was" as the same fact — is closed on the free path, and semantic reuse now demands the full answer and citations. The implementation is suitable for another independent review.

It is **not** ready for production. Do not apply migration `005` or `006` to production, deploy, push, or spend model budget until the live 600-call evaluation is approved and its false-reuse count on the held-out split is zero.
