# BookRAG cloud application integration — 24 October 2026

## Branch and source

Integration worktree: `/Users/manumathewjiss/Documents/Codex/bookrag-cloud-integration` on
`feat/bookrag-cloud-integration`. The backend came from commit `df827be`.
The frontend worktree was at `04231b1`; its `cloud_frontend/` files were present
only as untracked working files, so this branch contains an explicit snapshot of
that folder. Neither agent worktree was edited. No benchmark, books app, or database
was changed.

## What works locally

The Next.js UI at localhost:3001 called the real FastAPI routes at localhost:8765.
The test server replaced Supabase Auth, private Storage, PostgreSQL, Voyage, and
OpenAI with in-memory/test implementations. Its banner says this clearly.

Browser walkthrough: local test sign-in; empty private library; PDF upload; queued
to ready processing (2 pages, 2 passages); grounded question and PDF-page-2
citation; rendered private PDF page; reload and re-open the citation without any
IndexedDB upload cache; unanswerable question with no citation; delete confirmation;
empty library after deletion.

The private PDF route is `GET /api/v1/documents/{id}/pdf`. It requires a bearer
token, looks up the document for that authenticated owner, reads the private
server-generated storage path, and returns PDF bytes with `private, no-store`.
Other-user access and deleted documents return 404. The frontend fetches it using
the current token and never puts a storage service key in the browser.

Direct local HTTP checks: invalid token 401; another user's PDF 404; allowed
localhost CORS preflight 200; unlisted origin preflight 400. Existing backend
tests cover application usage limits and failed/uncertain ingestion recovery.

## Verification

- Backend: `27 passed`.
- Frontend: `20 passed`.
- TypeScript: `tsc --noEmit` passed.
- ESLint: `eslint src` passed.
- Next.js production build: passed, seven routes generated.
- No live provider request, paid resource, deployment, or database migration.

## Still needs a controlled cloud verification

1. Connect actual Supabase Auth, Storage, and PostgreSQL. Test sign-up, token
   refresh/expiry, RLS, two real users, private PDF fetch after a new browser
   sign-in, and migration execution.
2. Exercise the separate Render worker with real queue and storage persistence,
   including crash/retry and operator review of uncertain embedding batches.
3. Verify Voyage embedding/reranking and Sol answer parsing on small approved
   calls. This sprint used deterministic mock outputs, not answer-quality evidence.
4. Set actual Vercel and Render origins in `ALLOWED_ORIGINS`; verify CORS and
   deployment secrets in an approved environment.
5. Browser tests for a real failed ingestion and exhausted rate/usage limits
   still need the cloud backing services. Offline backend tests cover those rules.

The local test auth switch (`NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH=true`) is
disabled in production builds and must never be used as a deployment login.
The test server in `cloud_backend/tests/local_integration_server.py` must not
be deployed.
