# BookRAG cloud frontend

Next.js + TypeScript UI for the private multiuser PDF library and RAG chat.
The consolidated deployment-readiness worktree includes the matching FastAPI
backend. The live local BookRAG application remains separate.

## Stack

- React 19, Next.js 15 App Router, TypeScript
- Supabase Auth (anon/public key only in the browser)
- Typed client for Codex `API_CONTRACT_v1.md`
- Authenticated `GET /api/v1/documents/{id}/pdf` for the viewer (Bearer token, `cache: no-store`). The backend reads the owner's private Supabase Storage object. The viewer can reopen an uploaded PDF after reload or on another signed-in device; it does not depend on an IndexedDB-only copy.

## Local run

```bash
cd cloud_frontend
cp .env.example .env.local
# For UI-only work without Supabase, set NEXT_PUBLIC_BOOKRAG_USE_MOCK=true
npm install
npm test
npm run lint
npm run typecheck
npm run dev
```

Open http://localhost:3000. Real sign-in requires `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (anon key, never service role).

## Production / Vercel

Root directory: `cloud_frontend`. Framework: Next.js.

Set in Vercel **Production**:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `NEXT_PUBLIC_BOOKRAG_API_URL` | Public FastAPI origin |

Leave mock flags unset or `false`. A production build **fails** if either mock
flag is true, a required public setting is missing, or the service addresses
are not HTTPS. Use the real Supabase public key and the real FastAPI URL.

Never set `SUPABASE_SERVICE_ROLE_KEY`, `VOYAGE_API_KEY`, `OPENAI_API_KEY`, or
`DATABASE_URL` on the frontend project.

Backend `ALLOWED_ORIGINS` must include the exact Vercel URL. Add
`http://localhost:3000` only while running a local browser against that backend.

Do not deploy until Manu approves.
