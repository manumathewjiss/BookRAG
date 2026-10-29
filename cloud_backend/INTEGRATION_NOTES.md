# Backend sprint integration report

## Implemented in this sprint

- Migration `002_embedding_checkpoints.sql` stores every batch's input hash, pending state, successful vectors, and token usage. The pending row is committed **before** the provider request. Completed rows are reused on retry; usage is recorded in the same database transaction as a successful checkpoint.
- A worker lease token prevents an old worker from saving results after another worker takes the job. The worker renews its lease before each batch. Expired pending calls are quarantined as `attention` instead of automatically replayed.
- A definite provider rejection such as HTTP 429 clears only that pending batch, then uses the job's retry delay. Timeouts, 5xx responses, and interrupted calls are treated as uncertain. Operator-only recovery can retry a definite failure or clear an uncertain batch **after checking that the provider did not process it**.
- Upload count is checked atomically under a per-user database lock. Questions have atomic daily, per-minute, and estimated daily usage reservations. Failed hosted calls keep their reservation; this is conservative.
- Mocked end-to-end test exercises Supabase Auth, private Storage, upload, worker ingestion, Voyage embeddings, hybrid search, Voyage reranking, Sol answer, PDF-page citation, deletion, and a second user denied access.
- Two-page PDF tests verify one-based page references and no cross-page chunks. The [chunking comparison](CHUNKING_COMPARISON.md) explains differences from the frozen research method.

## What remains before deployment

1. Apply migrations to an approved Supabase test project. Test real database transactions, RLS, private Storage, and Auth using two accounts. This sprint used mocks, not a cloud project.
2. Run an explicitly approved small real-provider end-to-end check. No hosted model API call was made here.
3. Freeze a new uploaded-PDF evaluation set. The historical 150/32-question scores used different chunks and do not establish cloud-upload accuracy.
4. Verify provider limits and account-level billing caps. The application estimate is not a hard provider billing limit.
5. Test Render's web and worker memory, connection pooling, object size behavior, job lease timing, and CORS with the actual frontend origin.
6. Review the operational procedure for uncertain embedding batches. A missing provider response cannot be recovered automatically without risking a duplicate charge.

No frontend-owned files, frozen research data, historical results, live BookRAG app, or live database were changed.
