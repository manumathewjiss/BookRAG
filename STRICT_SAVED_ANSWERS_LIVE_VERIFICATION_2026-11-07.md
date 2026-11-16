# Strict Saved Answers v1: live verification, 2026-11-07

## Scope

The owner replaced the expired OpenAI API key in Render. The existing `bookrag-api` service then showed a new Live deployment, `dep-dbnq19c9v7es73deouc0`, still on reviewed commit `c2973d8f0f3e8dd8f3a0401c6c75864c6ecb7d04`. No application code, database migration, PDF, or Storage object was changed as part of this test. The existing Apollo 11 PDF was used; no upload or deletion occurred.

## Results

| Check | Result |
| --- | --- |
| API and signed-in library | API health returned `ok`; the library loaded the owner's ready 254-page Apollo 11 PDF. |
| First new answer | “Who was the commander of Apollo 11?” returned Neil A. Armstrong, with a citation to PDF page 142. The cited passage explicitly says “Commander, Apollo 11.” Normal search, rerank, and answer timings were shown. |
| Exact repeat | Same answer text; “Previously answered” appeared; rerank and answer timings were zero. |
| Whitespace/question-mark variant | Same answer text; “Previously answered” appeared; rerank and answer timings were zero. |
| Meaningfully different question | “Who was the command module pilot of Apollo 11?” ran the normal pipeline and returned Michael Collins, with a citation to PDF page 144. The cited passage explicitly says “Command Module Pilot, Apollo 11.” |
| Saved-answer database | Two rows for the tested PDF after the two new questions. |
| Usage accounting | The two repeat rows were `saved-answer-reuse`, each with zero input tokens, zero output tokens, and $0 estimated cost. The two new answer rows were normal Voyage + OpenAI usage. The code returns before model calls on a saved hit. |
| Cross-user UI check | The signed-in tester opened the known ID of a PDF owned by a different account; the Ask page returned “Document not found.” No question was submitted to that PDF. This is a UI/access check, not a fresh direct 404 test of download, question, and delete endpoints. |
| Existing data | Three ready documents, 14 deleted records, 757 total passages, and three private Storage objects remained. The tested PDF stayed ready with 254 pages and 334 passages. |

The saved answer and citation displayed for the commander repeat matched the first answer. The citation panel showed PDF page 142. The pilot answer cited page 144. This review did not independently compare raw API response JSON or provider request IDs.

## Cost and limits

Exactly **two new answer pipelines** were submitted, within the approved two-request maximum. The application estimated **$0.005117** for the commander answer and **$0.005306** for the pilot answer, totaling **$0.010423**. Both cache hits recorded **$0** and zero tokens. These are application estimates, not an invoice.

The new OpenAI key showed a last-used date after testing, but its key-filtered usage dashboard still showed no data immediately afterward. Provider charges can appear later. Voyage billing was not independently checked here. Therefore, actual provider cost and provider-side zero-call confirmation remain pending; do not report the estimate as a settled charge. The application records and inspected code support zero model calls on cache hits.

## Verdict

The live site successfully generated two grounded answers, reused the same answer for an exact and formatting-only repeat, and ran a new pipeline for a different question. The deployed Saved Answers behavior is **functionally verified for this bounded smoke test**. Remaining verification is provider-billing reconciliation and, if required for a full security sign-off, fresh direct 404 checks for another user's download, question, and delete endpoints. The earlier two-user isolation test remains documented separately.
