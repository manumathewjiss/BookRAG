# BookRAG Cloud Backend

This is an isolated backend implementation. It does not import or modify the local Flask demo, historical benchmark, or frozen evaluation files. No API call is made when modules are imported or tests run.

## Cursor integration

The stable browser contract is [API_CONTRACT_v1.md](API_CONTRACT_v1.md). Send the Supabase user access token in `Authorization: Bearer ...`; never send a user ID or service role key from the browser. The frontend can use Supabase Auth directly, then call these routes. Poll document status before allowing chat.

## Local development

Copy `.env.example` to a local `.env` and fill it privately. Run `pip install -r requirements.txt`, then `uvicorn bookrag_cloud.main:app --reload`. Start a separate worker with `python -m bookrag_cloud.worker`. The application will not work end-to-end until the Supabase project, private Storage bucket, and SQL migration exist. The code does not provision them.

Apply `migrations/001_initial.sql` in the target Supabase project only when deployment is approved. Configure a direct/pooled PostgreSQL URL with SSL. Keep its credential, the Supabase service role key, and provider keys on the server only. Use `pytest` for offline tests.

## Retrieval fidelity

The production candidate pool copies the frozen benchmark's tokenization (`Unicode \w+`, casefold), BM25 constants (`k1=1.2`, `b=0.75`), dense top 30 + BM25 top 30, reciprocal-rank score with 60, and final top 20. It computes BM25 over the selected document's passages in the worker process memory at question time. This is an exact ranking formula, not PostgreSQL full-text scoring. At a 3,000-passage document cap, it is suitable for an initial small trial; profile before expanding limits. The index uses pgvector exact cosine distance. Voyage reranks the same 20 full passages and Sol receives five.

PDF extraction uses pypdf and 450-token chunks with 50-token overlap, split separately within each PDF page. This is intentionally page-aware for citations, but differs from historical Stage 1 chunks; it requires a new evaluation before claiming the frozen benchmark's accuracy on newly uploaded files. Image-only PDFs have no OCR and fail with a clear status.

## Reliability and security notes

The worker claims durable PostgreSQL jobs and retries failures up to three times. Deleting a document removes its private source and its indexed passages; document IDs are always scoped to the authenticated Supabase user. Server-side query and upload limits are basic trial safeguards, not billing caps. Provider charges still need account-level limits. Citations are only from the five sent passage IDs, with page numbers from database metadata. When Sol says the evidence is missing, the API returns no citations.

The backend has not been deployed or tested against a real Supabase project in this sprint. See `INTEGRATION_NOTES.md` for the remaining validation gates.
