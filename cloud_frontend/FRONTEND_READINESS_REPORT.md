# BookRAG frontend production-readiness — 26 October 2026

Branch: `feat/bookrag-cloud-frontend-readiness`  
Base: `feat/bookrag-cloud-integration` commit `5c2e63c`  
Worktree: `/Users/manumathewjiss/Documents/Codex/bookrag-cloud-frontend-readiness`  
Backend files were not modified.

## Changes

- Mock API and local test auth are **forced off** in production (`NODE_ENV` / `VERCEL_ENV`). Production `next build` throws if those flags are true.
- Public env flags are read with static `process.env.NEXT_PUBLIC_*` member access so Next inlines them into the client bundle. Dynamic `process.env[name]` left SSR on mock while the browser thought Auth was unconfigured.
- `next.config.ts` no longer imports `src/lib/config` (that import also broke client env inlining).
- Supabase Auth: session restore, `onAuthStateChange`, refresh when JWT expiry is within 60s, login `?next=` allowlist (`/library`, `/chat` only), logout returns to `/login`, 401 signs out.
- Live client refuses `mock.local.*` tokens. Bearer header only. Private PDF download uses `GET /api/v1/documents/{id}/pdf` with `cache: "no-store"`.
- Middleware protects `/library` and `/chat` when Supabase is configured and sends signed-in users away from `/login` and `/signup`.
- Vercel config + security headers. Env template lists only public values.
- Service-role JWT pasted into the anon key is rejected (`looksLikeServiceRoleKey`).
- Mobile: 44px targets, sticky ask row, truncated email, PDF scale, safe-area padding.
- `unverified` evidence badge; answers are withheld when evidence is unverified. Viewer errors use API messages.
- IndexedDB PDF cache removed. The viewer always fetches through the authenticated client (`getPdf`), never a local blob store.
- pdf.js worker is copied to `public/pdf.worker.min.mjs` at Next config load (gitignored) so the authenticated viewer does not fail module resolution in Next 15.

## Browser checks (mock API, 26 Oct 2026)

Independent `curl` of `/login` shows mock-only copy. The stale “Add NEXT_PUBLIC_SUPABASE_URL…” / “Supabase Auth is not configured” split is not reproducible after the env-inline fix.

| Flow | Result |
| --- | --- |
| Login | Pass. Mock-only banner; sign-in reaches `/library`. |
| Document library | Pass. Seed docs listed; status Ready. |
| PDF upload | Pass. `notes.pdf` became Ready in the same mock session. |
| Browser reload | Pass. Session kept. Mock uploads vanish after full reload because the mock client is in-memory (expected). |
| Chat | Pass. Grounded Think Python answer with timings. |
| Citations | Pass. Two page-23 evidence chips. |
| Authenticated PDF viewer | Pass. Citation opens canvas via `client.getPdf`; mock page clamped to 1/1. |
| Logout | Pass. Lands on `/login`. |
| Mobile ~390×844 | Pass. Library and chat stack to one column; 44px ask/delete targets. |

## Not done here (Codex / Manu)

- Provisioning a real Supabase project, Render API, or Vercel project
- Deploy
- Paid provider calls
- Backend CORS `ALLOWED_ORIGINS` for the eventual Vercel host
- Live (non-mock) E2E against a real API and real PDFs
