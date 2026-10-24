# BookRAG Cloud Backend

This is an isolated backend implementation. It does not import or modify the local Flask demo, historical benchmark, or frozen evaluation files. No API call is made when modules are imported or tests run.

## Cursor integration

The stable browser contract is [API_CONTRACT_v1.md](API_CONTRACT_v1.md). Send the Supabase user access token in `Authorization: Bearer ...`; never send a user ID or service role key from the browser. The frontend can use Supabase Auth directly, then call these routes. Poll document status before allowing chat.

## Local development

Copy `.env.example` to a local `.env` and fill it privately. Run `pip install -r requirements.txt`, then `uvicorn bookrag_cloud.main:app --reload`. Start a separate worker with `python -m bookrag_cloud.worker`. The application will not work end-to-end until the Supabase project, private Storage bucket, and SQL migration exist. The code does not provision them.

Apply `migrations/001_initial.sql` in the target Supabase project only when deployment is approved. Configure a direct/pooled PostgreSQL URL with SSL. Keep its credential, the Supabase service role key, and provider keys on the server only. Use `pytest` for offline tests.

## Retrieval fidelity

The production candidate pool copies the frozen benchmark's tokenization (`Unicode \w+`, casefold), BM25 constants (`k1=1.2`, `b=0.75`), dense top 30 + BM25 top 30, reciprocal-rank score with 60, and final top 20. The API computes BM25 over the selected document's passages in memory at question time. This is an exact ranking formula, not PostgreSQL full-text scoring. At a 3,000-passage document cap, it is suitable for an initial small trial; profile before expanding limits. The index uses pgvector exact cosine distance. Voyage reranks the same 20 full passages and Sol receives five.

PDF extraction uses pypdf and 450-token chunks with 50-token overlap, split separately within each PDF page. This is intentionally page-aware for citations, but differs from historical Stage 1 chunks; it requires a new evaluation before claiming the frozen benchmark's accuracy on newly uploaded files. Image-only PDFs have no OCR and fail with a clear status.

## Reliability and security notes

The worker claims durable PostgreSQL jobs and records each Voyage embedding batch before the hosted request. Completed batches are reused after restart. An uncertain pending request enters operator review and is never automatically resent. A definite 429 response permits retry of that batch. See `python -m bookrag_cloud.recovery --help` for operator-only recovery after confirming provider usage. Apply both SQL migrations in order. Deleting a document removes its private source and indexed passages; document IDs are scoped to the authenticated Supabase user. Server-side question/upload limits and estimated usage reservations are trial safeguards, not provider billing caps. Citations are only from the five sent passage IDs, with pages from database metadata. When Sol says evidence is missing, the API returns no citations.

See [CHUNKING_COMPARISON.md](CHUNKING_COMPARISON.md) for the exact difference between frozen research chunks and newly uploaded PDF chunks.

The backend has not been deployed or tested against a real Supabase project in this sprint. See `INTEGRATION_NOTES.md` for the remaining validation gates.
