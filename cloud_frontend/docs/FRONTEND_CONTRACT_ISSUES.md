# Frontend–backend contract notes (26 Oct 2026)

Canonical contract: Codex `cloud_backend/API_CONTRACT_v1.md`.
Consolidated worktree: `feat/bookrag-cloud-deployment-readiness`.

## Aligned in this frontend

- Auth is a Supabase access token only. The browser never sends `user_id`.
- DELETE 204 is success. DELETE 404 is treated as already gone.
- Error envelope `{ error: { code, message } }` with FastAPI `detail` string fallback.
- Evidence status includes `unverified`. The UI withholds that answer and does not
  offer citations.
- Chat 409 `still_processing` is shown as an error; the UI polls document status,
  not chat.

## Resolved integration points

1. **Private PDF download.** The backend implements and documents
   `GET /api/v1/documents/{id}/pdf`. The frontend sends Bearer + `cache: no-store`.
   Backend tests confirm the owner receives the original bytes and another user
   receives 404. No IndexedDB copy is required after a reload or on another device.
2. **CORS vs 403.** Disallowed origins are blocked by CORS, not a 403 JSON body.
   The frontend maps HTTP 403 to `forbidden` if a body appears.
3. **`ALLOWED_ORIGINS`.** Must include `http://localhost:3000` and the eventual
   Vercel origin before a real browser can call FastAPI.
4. **Usage object.** `usage.estimated_usd` is informational. The UI does not display
   a billing cap.
5. **Token refresh.** Frontend refreshes when JWT `exp` is within 60 seconds.
   Backend still validates the token it receives.
6. **Local integration auth** (`NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH`) is
   development-only. Production builds reject it and mock mode; the test FastAPI
   server must not be deployed.
7. **Production configuration.** The production build requires the Supabase URL,
   public key, and HTTPS FastAPI origin; missing or placeholder values fail the build.

## Browser secrets

The frontend bundle is allowed: `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (anon/public only), `NEXT_PUBLIC_BOOKRAG_API_URL`.
Never `SUPABASE_SERVICE_ROLE_KEY`, `VOYAGE_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL`.
