# BookRAG Semantic Saved Answers — Technical Review Pack

**Audience:** Independent ChatGPT review  
**Branch:** `feat/semantic-saved-answers` (local only; not pushed)  
**Date:** 2026-11-05  
**Paid API calls in this work:** **0** (all results below marked SIMULATED/ESTIMATED where applicable)

---

## 1. Beginner-friendly explanation

BookRAG already saved answers so repeating the **same wording** could return the prior answer for free.

The professor’s requirement is harder: recognize **the same question asked differently**, return the **exact same answer text and citations**, but **never** reuse when the meaning changed (first vs second, who vs when, etc.).

**What we built (precision-first cascade):**

1. **Free Stage 0:** Exact/normalized match, then the old rule-based identity matcher.
2. **Paid Stage 1 (small):** Create one Voyage embedding of the new question → find nearby saved questions with pgvector → ask a small OpenAI model with a **strict structured yes/no** (“are these the same information request?”).
3. **Reuse only if the verifier says yes with high confidence.** Similarity score alone never authorizes reuse.
4. If not equivalent (or anything is uncertain/broken): run normal RAG. The **same** embedding is reused for document search (no second Voyage call).
5. Newly generated answers are saved with their question embedding so future paraphrases can find them.

**Analogy:** Stage 0 is a spelling checker for questions. Stage 1 is a careful teaching assistant who reads both questions and the saved answer before allowing a copy-paste reuse.

---

## 2. Exact files changed and why

| File | Why |
|------|-----|
| `SEMANTIC_SAVED_ANSWERS_IMPLEMENTATION_PLAN.md` | Concise plan before coding |
| `SEMANTIC_SAVED_ANSWERS_REVIEW.md` | This review pack |
| `cloud_backend/migrations/005_saved_answer_question_embeddings.sql` | Additive schema for embeddings + policy version |
| `cloud_backend/bookrag_cloud/equivalence.py` | Decision schema, validation, `MATCH_POLICY_VERSION` |
| `cloud_backend/bookrag_cloud/offline_equivalence.py` | Deterministic offline oracle (tests/benchmarks only) |
| `cloud_backend/bookrag_cloud/providers.py` | `verify_question_equivalence` via OpenAI structured output |
| `cloud_backend/bookrag_cloud/config.py` | Feature flag, verifier model, candidate knobs |
| `cloud_backend/bookrag_cloud/repository.py` | Vector candidate search; persist embedding on save |
| `cloud_backend/bookrag_cloud/main.py` | Cascade wiring; embed reuse; semantic settle accounting |
| `cloud_backend/benchmarks/semantic_saved_answers_cases.json` | Labeled eval set |
| `cloud_backend/benchmarks/run_semantic_saved_answers_benchmark.py` | Offline benchmark runner |
| `cloud_backend/benchmarks/semantic_saved_answers_benchmark_results.json` | Generated offline results |
| `cloud_backend/tests/test_equivalence.py` | Validator + offline oracle unit tests |
| `cloud_backend/tests/test_semantic_saved_answers.py` | Cascade integration tests (simulated providers) |
| `cloud_backend/tests/test_saved_answers.py` | Test doubles updated for new APIs |
| `cloud_backend/tests/test_api.py` | Fake repo/models updated |
| `cloud_backend/tests/test_mocked_cloud_flow.py` | Fake repo updated |

**Frontend:** No code changes required; existing `reused_answer` badge already covers semantic hits.

---

## 3. Database schema and migration changes

### Existing (still required): `004_saved_answers.sql`

Creates `saved_answers` with uniqueness on `(owner_id, document_id, question_canonical, document_sha256, pipeline_version)`. **Not applied to production** per latest status.

### New additive: `005_saved_answer_question_embeddings.sql`

```sql
alter table public.saved_answers
  add column if not exists question_embedding vector(1024);

alter table public.saved_answers
  add column if not exists match_policy_version text not null default 'rules-v1';

create index if not exists saved_answers_semantic_lookup_idx
  on public.saved_answers (owner_id, document_id, document_sha256, pipeline_version)
  where question_embedding is not null;
```

**Ordering:** `001 → 002 → 003 → 004 → 005`.  
**Rollback:** Drop index + columns (or restore DB snapshot). No destructive rewrite of answer text/citations.

**Policy versions:**

- `ANSWER_PIPELINE_VERSION` — invalidates answers when retrieval/answer models/prompts change.
- `MATCH_POLICY_VERSION` (`semantic-v1+gpt-6-luna`) — records matching/verifier policy for audit; live verify always re-runs (cosine never authorizes).

---

## 4. Complete request-flow diagram

```text
POST /api/v1/documents/{id}/chat
  │
  ├─ Auth (Supabase JWT)
  ├─ Load document; require owner + status=ready
  ├─ Acquire answer_lock(owner, document)   [prevents duplicate paid generation]
  │
  ├─ Stage 0 (free)
  │    ├─ exact canonical match? ──yes──► reserve → settle $0 → return EXACT saved answer+citations
  │    └─ rule identity rephrase? ─yes──► same as above
  │
  ├─ reserve_question (daily/minute/USD limits)
  │
  ├─ Voyage embed(question)  [ONCE]
  │
  ├─ Stage 1 (semantic) if enabled
  │    ├─ pgvector nearest saved questions
  │    │    filter: same owner, document, sha256, pipeline_version
  │    │    soft max_distance prefilter ONLY (never authorizes)
  │    ├─ for each candidate:
  │    │    OpenAI structured verify (default gpt-6-luna)
  │    │    invalid/uncertain/provider error → treat as RUN_FULL_RAG for that candidate
  │    └─ REUSE_EXACT_ANSWER + high confidence?
  │         yes → settle(embed+verify) → return EXACT saved answer+citations
  │
  ├─ Full RAG (reuse same query embedding)
  │    dense + BM25 + RRF → rerank-3 → gpt-6.1-sol → citation validation
  │
  ├─ settle_question (full costs including any verify tokens)
  ├─ save_answer best-effort (with question_embedding + MATCH_POLICY_VERSION)
  │    cache write failure → still return generated answer
  └─ release lock
```

**Decisions implemented:** `REUSE_EXACT_ANSWER` | `RUN_FULL_RAG` only (no evidence-only reuse).

---

## 5. Comparison against the original matcher

| Capability | Rules-only (`question_match`) | Semantic cascade (this work) |
|------------|-------------------------------|------------------------------|
| Exact repeat | Yes, $0 | Yes, $0 (Stage 0) |
| “Who is/was Neil Armstrong?” | Yes | Yes (Stage 0) |
| Professor lunar paraphrase | **No** | **Yes** (Stage 1 + verifier) |
| Synonym “human/person” | **No** | **Yes** (offline oracle; live TBD) |
| First vs second | Correctly rejects | Correctly rejects (critical) |
| Who vs when/why | Correctly rejects | Correctly rejects |
| Cost on paraphrase hit | N/A (miss → full RAG) | Embed + cheap verify ≪ full RAG |
| False reuse risk | Low (too strict) | Low if verifier strict; cosine alone forbidden |

Offline benchmark (n=18): rules recall **0.50**, semantic offline oracle recall **1.00**, both precision **1.00**, both false reuse **0**.

---

## 6. Benchmark results (explicit sample sizes / error counts)

**Result kind:** `SIMULATED_OFFLINE` — **0 paid API calls**.  
**Harness:** `cloud_backend/benchmarks/run_semantic_saved_answers_benchmark.py`  
**Cases:** 18 labeled examples in `semantic_saved_answers_cases.json`.

| Matcher | n | Precision | Recall | False reuse | Hard-neg false reuse | Avg latency |
|---------|---|-----------|--------|-------------|----------------------|-------------|
| rules_v1 | 18 | 1.000 | 0.500 | **0** | **0** / 12 | ~0.03 ms |
| semantic_v1_offline_oracle | 18 | 1.000 | 1.000 | **0** | **0** / 12 | ~0.03 ms |

Hard negatives covered: first vs second, entity swap, negation, who/when/why, Apollo 11 vs 12 quantity, different fact, refusal mismatch, different PDF/user, SHA change, pipeline change.

**Release gate used here:** `hard_negative_false_reuse_count == 0` for the semantic offline oracle.

**Important:** Passing this offline suite does **not** guarantee perfect live accuracy. Live Voyage+OpenAI evaluation requires spending approval and a separate report labeled `LIVE`.

---

## 7. Security and concurrency test results

All **simulated** (in-memory fakes / local pytest). No production DB.

| Test area | Result |
|-----------|--------|
| Backend pytest (`cloud_backend/tests`) | **68 passed** |
| Cross-user chat/delete cannot touch cache or models | pass (`test_cross_user_requests_do_not_touch_cache_or_paid_models`) |
| Different PDF isolation | pass |
| Digest / pipeline invalidation | pass (existing + benchmark isolation cases) |
| Cache write failure still returns paid answer | pass |
| Cache purge failure keeps PDF | pass |
| Concurrent equivalent requests → one paid pipeline | pass (`test_simultaneous_equivalent_requests_use_one_paid_pipeline`) |
| Semantic paraphrase reuses exact citations | pass (simulated verifier) |
| First vs second forces full RAG | pass |
| Verifier `None` → full RAG | pass |
| Exact path still $0 (no embed/verify) | pass |
| Frontend vitest | **50 passed** |
| Frontend `tsc --noEmit` | pass |
| Frontend `next build` | pass |

**Not run here:** live PostgreSQL advisory-lock stress against a real Supabase instance (feasible later; local Postgres recommended before prod).

---

## 8. Actual vs estimated API / infrastructure costs

| Item | Status |
|------|--------|
| Actual Voyage spend (this work) | **$0** |
| Actual OpenAI spend (this work) | **$0** |
| New hosting/services | **None** |
| Infra change | Schema columns + index only |

**Estimated Stage-1 probe cost** (SIMULATED assumptions in benchmark JSON):

- ~25 embed tokens + ~350/60 verify in/out tokens
- Default model pricing assumption: `gpt-6-luna`
- Assumed 70% of questions miss Stage 0 and probe Stage 1
- **~$0.0434 per 1,000 questions** for Stage-1 probes only (not full RAG)
- Cheaper `gpt-5-nano` estimate also computed, but **not selected** without live hard-negative accuracy comparison

Semantic **hits** avoid full `rerank-3` + `gpt-6.1-sol`, which dominates cost today.

---

## 9. Known limitations and unresolved risks

1. **Live verifier accuracy unknown** until a bounded paid eval is approved.
2. **Offline oracle ≠ production model** — recall/precision above are for the deterministic rubric stand-in.
3. **`answer_lock` still spans embed+verify+RAG** in v1 — correct for duplicate suppression; can lengthen wait under load. Safer finer-grained claim tokens are a follow-up.
4. **Candidate recall depends on embeddings** — if Voyage places a hard paraphrase far away, Stage 1 never sees it (fail-safe: full RAG, not false reuse).
5. **Rows saved before 005** lack embeddings until re-asked (or backfilled).
6. **004+005 not on production yet** — deploy ordering matters.
7. **Default verifier `gpt-6-luna`** chosen for structured-output + cost balance; must be confirmed against current OpenAI availability/pricing in a live bakeoff vs `gpt-5-nano`.
8. Benchmark n=18 is purposeful but small; expand before claiming production readiness.

---

## 10. Staged production deployment and rollback plan

**Do not execute without explicit approval.**

### Stage A — Local / preview

1. Keep branch `feat/semantic-saved-answers` unmerged until review.
2. Apply **004 then 005** on a **non-production** Supabase/Postgres.
3. Run backend pytest + offline benchmark (hard-neg false reuse must stay 0).
4. Optional: request approval for a **bounded live eval** (e.g. ≤50 verifier calls, fixed case list).

### Stage B — Production schema (maintenance window)

1. Confirm backups.
2. Apply `004_saved_answers.sql` if not present.
3. Apply `005_saved_answer_question_embeddings.sql`.
4. Verify RLS still denies anon/authenticated direct access; backend uses private DB role.

### Stage C — App rollout

1. Deploy API with `semantic_saved_answers_enabled=true` (or start `false` and flip after soak).
2. Watch: cache hit rate, false-reuse reports, verify error→RAG rate, p95 latency, USD/day.
3. Frontend unchanged.

### Rollback

1. Set `semantic_saved_answers_enabled=false` (Stage 0 rules-only remains).
2. Or redeploy previous API image.
3. Schema rollback optional: columns are additive; leaving them is safe.
4. Do **not** delete `saved_answers` rows to “fix” semantics — that would discard exact-match value.

### Merge/push policy

- **No push/merge to deployment branch** without approval.
- **No Render/Vercel deploy** from this workstream without approval.
- **No paid API calls** without approval.

---

## Verifier choice (for review)

| Criterion | Notes |
|-----------|-------|
| Integration | Existing OpenAI `/v1/responses` + strict JSON schema |
| Default | `gpt-6-luna` via `Settings.equivalence_model` |
| Alternative | `gpt-5-nano` (cheaper estimate; accuracy unproven live) |
| Fail closed | Invalid JSON, low confidence, inconsistent signals → `RUN_FULL_RAG` |
| Rubric | Same information request; stored answer+citations must satisfy unchanged |

---

## How to reproduce offline checks

```bash
cd cloud_backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q
.venv/bin/python benchmarks/run_semantic_saved_answers_benchmark.py
# --live is intentionally refused without spending approval
```

```bash
cd cloud_frontend
npm test && npm run typecheck && npm run build
```
