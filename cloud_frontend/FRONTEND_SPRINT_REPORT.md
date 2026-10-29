# BookRAG frontend sprint report — 24 October 2026

Branch / worktree: `feat/bookrag-cloud-frontend` at
`/Users/manumathewjiss/Documents/Codex/bookrag-cloud-frontend`
(sparse checkout, `cloud_frontend/` only). Codex backend worktree was not edited.

## Validation

- `npm test`: **19 passed / 6 files**
- `npm run build`: Next.js 15.5.28, **compiled, linted, typed, 7 routes generated**
- Browser (localhost:3000, mock mode): landing → login → library → chat → grounded answer → clickable citation → PDF viewer region

## Completed in this sprint

1. Login / signup / logout. Protected `/library` and `/chat`. Supabase Auth when anon URL+key are set; otherwise a clearly labeled mock-local session.
2. User dashboard + private PDF library with status badges, usage meters, empty states.
3. Drag-and-drop PDF upload with type/size/magic validation and queued → processing → ready polling.
4. Document selection, delete confirmation, and API error cards.
5. Chat with local question history, loading copy, answer formatting, and refusal (`enough_evidence=false`, `evidence_status=absent`).
6. Clickable citations: filename, PDF page, supporting excerpt.
7. pdf.js viewer for the cited page, using the file cached in IndexedDB at upload time (v1 API does not serve PDF bytes).
8. Responsive desk layout (library/chat stack under 900px), skip link, dialog focus, `aria-pressed`, `aria-live`.
9. Typed client matching Codex `API_CONTRACT_v1.md`. Bearer token only; no service-role key; no user id sent from the browser.
10. Vitest tests, `.env.example`, `vercel.json` (root directory `cloud_frontend`). Not deployed.

Visual language reused from `books/demo/templates/index.html` (ivory / navy / brass). Vanilla `frontend/` Sanskrity UI was not mixed in.

## Mock vs live

`NEXT_PUBLIC_BOOKRAG_USE_MOCK=true` (default). Amber banner: **Mock API. Isolated frontend responses — not live BookRAG retrieval.**

Set `NEXT_PUBLIC_BOOKRAG_USE_MOCK=false` only when Codex `/api/v1/health`, documents, and chat accept authenticated traffic.

## Integration blockers (Codex / Manu)

| Blocker | Needed |
|---|---|
| FastAPI `/api/v1` routes are still incomplete in the backend worktree (contract + schemas exist; no live chat/upload server wired for the UI) | Health, me, documents CRUD, chat matching the contract error envelope |
| No private PDF download in v1 | Viewer depends on the browser-cached upload; add a signed file route later if needed |
| Supabase project URL + **anon** key not in this app yet | Auth stays mock-local until keys are provided. Service role must stay on the backend |
| CORS `ALLOWED_ORIGINS` | Include `http://localhost:3000` and the eventual Vercel origin |
| Error envelope | Contract uses `{ error: { code, message } }`; current FastAPI `HTTPException(detail=string)` is accepted as a fallback |
| Daily limits 5 uploads / 50 questions | Frontend displays `/me` counters; enforcement is backend |
| Deploy / billing | Vercel config is present; no deploy was run |

## Out of scope (preserved)

Frozen benchmark and evaluation outputs were not touched. No local Qwen/PyTorch. No `books/` demo edits. No `cloud_backend/` edits. No API keys in browser code.
