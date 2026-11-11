# BookRAG deployment readiness — 26 October 2026

This branch consolidates backend readiness `5a283a7` (including the later local Supabase sign-in helper) and frontend readiness `ed66af28a8b2e0db0cf66839d9a35538271dcf52`, both derived from integration `5c2e63c`. The existing local `books/` demo, research benchmarks, prior branches, ignored credentials, and live Supabase data were not changed. Nothing was deployed, provisioned, pushed, or sent to Voyage/OpenAI in this sprint.

## What is verified

- Earlier separately approved real-service smoke: upload, page-preserving indexing, original private PDF download, two-user isolation, page-2 grounded answer, abstention, deletion. It used five Voyage and two OpenAI requests; runner reserves were $0.000031 and $0.024928 respectively. This was not repeated. The fixture's storage object/passages/jobs were removed; a soft-deleted document record remains, so do not rerun the same first-run smoke against this project.
- Current offline suite: 33 backend tests and 42 frontend tests pass. Frontend lint, TypeScript, and production build pass with nonsecret example public URLs. Mock provider tests cover upload, worker, chat, citations, deletion, and different users. These do not prove Render/Vercel connectivity.
- The backend implements `GET /api/v1/documents/{id}/pdf` with bearer authentication, owner filtering, private Storage access and `Cache-Control: private, no-store`. Frontend retrieves this route after reload instead of requiring an IndexedDB copy. A different user receives 404 in tests.
- Production frontend builds now reject enabled mock/test-auth flags, missing public settings, HTTP service origins, and a Supabase secret/service-role key in the public key field. The test-only FastAPI server is separate from the Render command.
- FastAPI CORS uses exact values in `ALLOWED_ORIGINS`; no wildcard is configured. Supabase Auth checks bearer tokens, and document database calls scope by authenticated owner. The previous Supabase read-only security preflight passed seven checks.

## Exact deployment configuration (requires separate user approval)

1. **Supabase:** Reuse the existing production project. Migrations `001_initial.sql`, `002_embedding_checkpoints.sql`, `003_cloud_readiness.sql`, and `004_saved_answers.sql` are already applied. This release verifies that `public.saved_answers` is present with its unique key, lookup index, row-level security, and revoked browser grants. It does not reapply `004_saved_answers.sql`. It does not apply any later migration. Run `cloud_backend/scripts/supabase_preflight.py` read-only before deployment. Use a TLS Postgres URL. Do not grant browser access to the service-role key or private PDF bucket.
2. **Render:** Connect the deployment branch and select `cloud_backend/render.yaml` as Blueprint path (Render allows a custom path). It defines `bookrag-api` as a Docker web service and `bookrag-ingestion` as a Docker background worker, each on legacy `starter` = current `0.5c-512mb`, with auto-deploy off. Web health is `/api/v1/health`; worker command is `python -m bookrag_cloud.worker`. Both need the same database, Supabase URL, service-role key, and Voyage key. Only web needs OpenAI key and `ALLOWED_ORIGINS`. Set the storage bucket explicitly on both if it differs from `bookrag-pdfs`. Start the worker only after the web service and database checks succeed. Confirm 512 MB is enough during a representative PDF ingestion; this remains unmeasured on Render.
3. **Vercel:** Import the same approved commit, root directory `cloud_frontend`, Next.js framework, with `cloud_frontend/vercel.json`. Production public variables: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable/anon only), `NEXT_PUBLIC_BOOKRAG_API_URL` (HTTPS Render web origin). Keep both mock flags absent/false. Set Supabase Auth site URL and redirect allowlist to the exact deployed Vercel origin. Set Render `ALLOWED_ORIGINS` to that exact origin, plus local `http://localhost:3000` only if needed for local verification. Deploy Vercel after the Render URL exists; its public URL is compiled into the frontend build.
4. **Secrets:** `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `VOYAGE_API_KEY`, `OPENAI_API_KEY` are server-only. Add them through Render's secret environment settings, never to `NEXT_PUBLIC_*`, Git, or logs. The ignored `.env` and `verification_sessions.env` in the prior worktree remain there. This consolidated worktree intentionally has no copied secrets.
5. **Limits:** API upload/question/minute/estimated daily spend controls are application guards, not provider billing stops. Inspect actual provider balances and set dashboard budget alerts separately. Keep worker and web running the same commit and migrations.

## Deployment verification and recovery

1. Check health endpoint, Render worker startup, database connection with TLS, and read-only Supabase security preflight. Confirm no failed/attention embedding batch before upload.
2. Use two fresh signed-in test users. User A uploads a small two-page PDF; wait for ready. Check list/status, answer citing the correct PDF page, reload, and reopen the original private PDF. User B must fail to list/read/chat/delete A's document. Ask an unanswerable question and check abstention without a misleading citation. Delete A's document and confirm PDF route is 404, object removed, and no active passages/jobs. Check Render, Supabase, Voyage, and OpenAI usage dashboards afterward. Do not repeat the earlier paid fixture smoke.
3. If a deployment fails, disable new uploads/questions while investigating. Revert Vercel to its prior successful deployment and Render web **and worker** to the same prior commit; do not roll back only one service. This saved-answer release adds no migration, so rollback is a code redeploy of the previous commit. Leave `saved_answers` in place. Never reverse a database migration without reviewing live rows first. If an embedding batch is marked `attention`, inspect provider usage and the checkpoint before any retry; automatic replay can duplicate a paid request. Restore service only after health, Auth, worker state, and private access checks pass.
4. If Supabase Free pauses after inactivity or reaches capacity, resume/upgrade deliberately; do not silently move data. Keep a separate backup/export plan before accepting irreplaceable user PDFs. Current Free plan does not provide the paid backup guarantees.

## Five-user monthly cost (USD, pricing checked 26 Oct 2026)

| Item | Published price / rule | Pilot assumption |
|---|---|---:|
| Render web + worker | `0.5c-512mb` at $7 per service/month | $14/month, always on |
| Supabase Free | $0; 500 MB database, 1 GB file storage, pauses after inactivity | $0 while within limits |
| Vercel Hobby | $0; limited to personal, noncommercial use | $0 only if this pilot qualifies |
| Vercel Pro | $20/month, includes usage credit | $20 if Hobby is ineligible |
| Supabase Pro | from $25/month | $25 only if Free is insufficient |
| Voyage `voyage-4-large` + `rerank-3` | $0.12 and $0.05 per million tokens after eligible free allowance | usage-dependent |
| OpenAI `gpt-6.1-sol` Standard | $2 input / $10 output per million tokens | usage-dependent |

For **five users asking 100–250 total questions per month**, assume about 2,500 Sol input and 150 output tokens per question. That is about $0.65–$1.63 for Sol answers at list price, plus small Voyage query/rerank usage and occasional PDF ingestion. Budget **$2–$5/month for models** for this light pilot; this is a planning allowance, not a provider bill or hard cap. Thus an eligible noncommercial Free-tier pilot is roughly **$16–$19/month** ($14 Render + model allowance); with Vercel Pro, roughly **$36–$39/month**; with both Vercel Pro and Supabase Pro, roughly **$61–$64/month**. Taxes, traffic/egress overages, more PDFs, and provider usage beyond assumptions are additional. Do not treat five users as a performance guarantee on 512 MB Render services.

Pricing sources: [Render pricing](https://render.com/pricing), [Render compute plans](https://render.com/docs/compute-plans), [Vercel pricing](https://vercel.com/pricing), [Vercel Hobby rule](https://vercel.com/docs/plans/hobby), [Supabase pricing](https://supabase.com/pricing), [Voyage pricing](https://docs.voyageai.com/docs/pricing), [OpenAI Sol pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

## Remaining deployment blockers

- User approval to connect repository and create paid Render web + worker; no hosting resources exist yet. Confirm whether the pilot qualifies for Vercel Hobby or use Pro.
- Enter server secrets into Render and only public configuration into Vercel; configure Auth redirect URLs and exact CORS origin after URLs are known.
- Validate Render Blueprint and actual 512 MB worker memory/throughput with a controlled PDF. Verify database reachability from Render and actual browser calls from Vercel. Those cannot be proved by offline tests.
- Supabase Free capacity and pause behavior must be accepted or upgraded before relying on it for a continuing pilot. Confirm actual provider balances and alerts.
