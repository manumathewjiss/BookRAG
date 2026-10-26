# Frontend–backend contract notes (25 Oct 2026)

Canonical contract: Codex `cloud_backend/API_CONTRACT_v1.md`.
Frontend worktree: `feat/bookrag-cloud-frontend-readiness` from integration `5c2e63c`.
Backend files were not modified here.

## Aligned in this frontend

- Auth is a Supabase access token only. The browser never sends `user_id`.
- DELETE 204 is success. DELETE 404 is treated as already gone.
- Error envelope `{ error: { code, message } }` with FastAPI `detail` string fallback.
- Evidence status includes `unverified`. The UI withholds that answer and does not
  offer citations.
- Chat 409 `still_processing` is shown as an error; the UI polls document status,
  not chat.

## Confirmed gaps (Codex / infra)

1. **Private PDF download.** This frontend calls
   `GET /api/v1/documents/{id}/pdf` with Bearer + `cache: no-store`. Codex's current
   backend contract still says private PDF downloads are not exposed in v1. If that
   route is missing in production, the viewer cannot open cited pages.
2. **CORS vs 403.** Disallowed origins are blocked by CORS, not a 403 JSON body.
   The frontend maps HTTP 403 to `forbidden` if a body appears.
3. **`ALLOWED_ORIGINS`.** Must include `http://localhost:3000` and the eventual
   Vercel origin before a real browser can call FastAPI.
4. **Usage object.** `usage.estimated_usd` is informational. The UI does not display
   a billing cap.
5. **Token refresh.** Frontend refreshes when JWT `exp` is within 60 seconds.
   Backend still validates the token it receives.
6. **Local integration auth** (`NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH`) is
   development-only. The test FastAPI server must not be deployed.

## Browser secrets

The frontend bundle is allowed: `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (anon/public only), `NEXT_PUBLIC_BOOKRAG_API_URL`.
Never `SUPABASE_SERVICE_ROLE_KEY`, `VOYAGE_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL`.
