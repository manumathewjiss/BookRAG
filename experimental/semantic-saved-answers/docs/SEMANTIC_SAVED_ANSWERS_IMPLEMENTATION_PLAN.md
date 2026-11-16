# Semantic Saved Answers — Implementation Plan

**Branch:** `feat/semantic-saved-answers` (local only; no push/deploy)  
**Constraint:** No production DB, migrations, deploy, or paid API calls without approval.

## Design (precision-first cascade)

1. **Stage 0 (free):** Exact canonical match, then existing rule-based identity rephrase.
2. **Stage 1 (paid, small):** One Voyage query embedding → pgvector candidate fetch (same user/doc/SHA/pipeline) → structured OpenAI equivalence verifier.
3. **Authorize reuse only** when the verifier returns validated `REUSE_EXACT_ANSWER` with high confidence. Cosine distance never authorizes reuse (distance is only a candidate prefilter).
4. **On miss:** Reuse the same query embedding for dense retrieval; run full RAG; persist answer + question embedding + match policy version.
5. **Decisions in v1:** `REUSE_EXACT_ANSWER` | `RUN_FULL_RAG` only (no evidence-only reuse).
6. **Failures:** Verifier/provider/parse failure → `RUN_FULL_RAG`. Cache write failure never drops a paid answer.
7. **Accounting:** Exact/rule hits stay `$0` via `settle_reused_question`. Semantic hits settle embed + verify tokens. Full RAG settles full pipeline cost.

## Why this vs cosine-only or rules-only

- Rules alone miss professor paraphrases (“first person to walk” ↔ “first stepped onto the lunar surface”).
- Cosine alone risks first↔second and who↔when false reuse (critical errors).
- A cheap structured verifier adds a hard semantic gate while keeping the stack (Voyage + OpenAI + pgvector) unchanged.

## Files to add/change

| Change | Why |
|--------|-----|
| `migrations/005_saved_answer_question_embeddings.sql` | Additive columns; 004 may still be unapplied in prod |
| `bookrag_cloud/equivalence.py` | Policy version + decision validation |
| `bookrag_cloud/providers.py` | `verify_question_equivalence` |
| `bookrag_cloud/config.py` | Verifier model + candidate knobs |
| `bookrag_cloud/repository.py` | Vector candidate search; save embedding |
| `bookrag_cloud/main.py` | Cascade wiring; embed reuse |
| `tests/test_equivalence.py`, `test_semantic_saved_answers.py`, `benchmarks/` | Offline correctness + cost estimates |
| `SEMANTIC_SAVED_ANSWERS_REVIEW.md` | ChatGPT-shareable deliverable |

## Safety

- Keep `answer_lock` for duplicate-generation prevention (v1 accepts longer lock on semantic path; documented).
- Isolation by owner, document, SHA256, `ANSWER_PIPELINE_VERSION`.
- `MATCH_POLICY_VERSION` stored for audit/invalidation when the verifier rubric changes.
