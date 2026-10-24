# BookRAG cloud frontend

Next.js + TypeScript UI for the private multiuser PDF library and RAG chat.
Codex owns the FastAPI backend in the sibling worktree
`/Users/manumathewjiss/Documents/Codex/bookrag-cloud-backend/cloud_backend/`.

This folder lives on git branch `feat/bookrag-cloud-frontend` (sparse worktree).
Do not edit `cloud_backend/`, `books/`, or `bookrag_benchmark/`.

## Stack

- React 19, Next.js 15 App Router, TypeScript
- Supabase Auth (anon key only in the browser)
- Typed client for Codex `API_CONTRACT_v1.md`
- Isolated mock API until live `/api/v1` routes exist
- pdf.js viewer for cited pages (uses the file cached at upload time)

## Local run

```bash
cd cloud_frontend
cp .env.example .env.local
# Keep NEXT_PUBLIC_BOOKRAG_USE_MOCK=true until the backend is up.
npm install
npm test
npm run dev
```

Open http://localhost:3000 — sign in with any email/password (mock-local session)
or real Supabase credentials once `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` are set.

## Environment

See `.env.example`. Never put a Supabase service-role key, Voyage key, or OpenAI
key in this app. The backend verifies Bearer tokens.

## Vercel

Root directory: `cloud_frontend`. Framework: Next.js. Set the same public env
vars in the Vercel project. Do not deploy until Manu approves.

## Mock vs live

`NEXT_PUBLIC_BOOKRAG_USE_MOCK=true` (default) uses in-memory documents and
canned answers. The amber banner is required so this is never mistaken for live
retrieval. Set it to `false` only when Codex’s `/api/v1` health/documents/chat
routes accept authenticated traffic.

v1 does not download private PDFs. The viewer renders the blob cached in
IndexedDB from the user’s upload in this browser.
