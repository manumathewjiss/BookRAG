# Strict Saved Answers v1 — production release record

**Status: PARTIAL, awaiting replacement of the expired OpenAI API key.** The reviewed backend and frontend are deployed. Live answer generation and saved-answer reuse are not yet verified. Do not describe this release as fully validated.

## Deployed revisions

| Component | Current release | Previous deployment |
| --- | --- | --- |
| Render `bookrag-api` | `dep-dbn0jhugekts73el8sag`, commit `c2973d8f0f3e8dd8f3a0401c6c75864c6ecb7d04` | `dep-dbh212m7bikc7389aa8g`, commit `dc3c2df3a495312de70b142d74e69189d98269d1` |
| Vercel `bookrag-cloud` | `Gm2aKtLLW4W5E7SufPEedtU3br7z`, commit `c2973d8f0f3e8dd8f3a0401c6c75864c6ecb7d04` | `BcqoPE9m2NZqNTDeQqwUrNoK7jKC`, commit `6ed2054737b35829175b9732d42445c6c506a578` |
| Render ingestion worker | Unchanged | Unchanged |

The production URLs are `https://bookrag.vercel.app/` and `https://bookrag-cloud.vercel.app/`; the API is `https://bookrag-api.onrender.com/`. Migration `004_saved_answers.sql` was already present and was not reapplied. Migrations `005` and `006` were not applied. The released tree excludes the experimental semantic matcher.

## Data protection

A fresh custom-format PostgreSQL backup was made before deployment at `.private-backups/bookrag-strict-v1-2026-11-06/bookrag-pre-strict-v1.dump` (8,297,999 bytes; SHA-256 `dcfd781578eabe65b6d6a2ea87b19ef9304bfb657907b153e3b2233c3d25ff67`). PostgreSQL 18 `pg_restore --list` read the archive and listed the existing BookRAG tables. The older pre-004 backup and three private PDF copies were preserved. The database dump does not itself contain private Storage objects.

Before the smoke test: 3 ready documents, 14 deleted records, 757 passages, 186 usage events, and 0 saved answers. After the failed smoke question: 3 ready documents, 14 deleted records, 757 passages, 187 usage events, and 0 saved answers. No PDF, document, passage, or saved-answer record was deleted.

## Live checks completed

- Render reported the API release **Live**. `/api/v1/health` returned HTTP 200. An unauthenticated `/api/v1/me` request returned HTTP 401.
- Vercel reported the frontend release **Ready**. Both production domains returned HTTP 200. The signed-in library loaded its existing ready NASA Apollo 11 PDF, and the Ask page opened.
- The signed-in account could not open another user's existing PDF: the Ask page showed “Document not found.” No question was submitted to that PDF.
- One answerable smoke question was submitted on the owner's ready PDF. The API returned HTTP 503 with “Answer service is temporarily unavailable”; no answer or saved-answer row was created.
- Read-only provider diagnostic from the running API environment returned OpenAI HTTP 401 with error code `expired_secret_key`. The key value was not printed or copied into this report.
- The failed question's usage event was settled as `provider='rejected'`, with 6,817 recorded input tokens, 0 output tokens, and an application estimate of `$0.000341`. This estimate represents known Voyage usage; actual provider billing has not been independently reconciled. The OpenAI request was rejected before an answer was generated.

## Remaining release gate

The owner must replace the expired `OPENAI_API_KEY` in the existing Render `bookrag-api` service. Do not paste the key into chat or source control. After Render applies the change, confirm a read-only authenticated model-access check succeeds, then repeat the approved live smoke test under the $1 target budget: one new answer, identical repeat, whitespace/question-mark variant, one meaningful-word change, citation equality, `reused_answer` response flag, zero model calls on cache hits, and cross-user rejection. Recheck document and passage counts, API logs, and provider usage. Stop if any new integrity or security concern appears.

Application rollback is available through the previous deployment IDs above. Rolling back code does **not** repair an expired OpenAI credential. The `saved_answers` table should remain in place.
