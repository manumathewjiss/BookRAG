# Integration notes

## Implemented

- Versioned `/api/v1` contract, upload/list/status/delete/chat/health/me routes.
- Supabase Auth token verification and private Storage client; per-user database filtering and RLS policies.
- Durable ingestion queue and worker; page-aware text extraction; Voyage embeddings; pgvector storage.
- Benchmark-equivalent BM25 + dense retrieval, RRF top 20, Voyage rerank top five, Sol grounded JSON answer.
- Hosted provider usage capture, estimated per-question spend, upload/question limits, no citation on refusal.
- Dockerfile and Render blueprint. No resources were provisioned.

## Before cloud release

1. Create a Supabase test project and apply migration; verify Storage API methods and RLS with two real accounts.
2. Run one approved end-to-end PDF upload and question with real Voyage/Sol APIs; no paid calls were made here.
3. Compare production chunking and retrieval on a newly frozen holdout. Historical benchmark scores do not automatically transfer.
4. Strengthen job recovery for long documents: a worker killed after an embedding batch can repeat that batch on retry. Add durable per-batch checkpoints or provider idempotency where supported.
5. Add a storage deletion reconciliation job for unusual database/storage partial failures, and an account-level budget gate. Current limits are trial controls, not a guaranteed dollar cap.
6. Validate Render plan memory, worker runtime, Supabase connection pooling, and CORS origin before deployment.

No frontend-owned files, historical research files, or live database were changed.
