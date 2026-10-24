# BookRAG Cloud API v1 (frontend snapshot)

Canonical file lives on the Codex branch at
`/Users/manumathewjiss/Documents/Codex/bookrag-cloud-backend/cloud_backend/API_CONTRACT_v1.md`.
This copy is for the sparse frontend worktree. If they diverge, Codex's file wins.

Base path: `/api/v1`. JSON uses UTF-8. All protected routes require
`Authorization: Bearer <Supabase access token>`. The backend validates that token
with Supabase Auth; it never accepts a user ID from the browser.

## Common errors

`{ "error": { "code": "short_machine_code", "message": "Safe user-facing text" } }`.

HTTP 400 invalid input, 401 missing/invalid token, 403 disallowed origin, 404 another
user's or nonexistent document, 409 still processing, 413 oversized PDF, 429 usage
limits, 503 provider unavailable.

## Routes

| Method and path | Request | Response |
| --- | --- | --- |
| `GET /api/v1/health` | none | `{ "status": "ok" }` |
| `GET /api/v1/me` | Bearer token | `{ "user_id": "uuid", "daily_questions_used": 0, "daily_uploads_used": 0 }` |
| `POST /api/v1/documents` | `multipart/form-data`, field `file` (PDF), optional `title` | 202 `{ "document": Document }` |
| `GET /api/v1/documents` | Bearer token | `{ "documents": [Document] }` |
| `GET /api/v1/documents/{document_id}` | Bearer token | `{ "document": Document }` |
| `GET /api/v1/documents/{document_id}/pdf` | Bearer token | Private PDF bytes; 404 if owned by another user or deleted |
| `DELETE /api/v1/documents/{document_id}` | Bearer token | 204 |
| `POST /api/v1/documents/{document_id}/chat` | `{ "question": "8–1200 characters" }` | 200 `Answer` |

`Document`: `{ "id", "title", "filename", "status": "queued\|processing\|ready\|failed", "page_count", "passage_count", "error", "created_at", "updated_at" }`.

`Answer`: `{ "answer", "enough_evidence", "evidence_status": "direct_answer\|nearby_only\|absent", "citations": [Citation], "timings_ms", "usage" }`.

`Citation`: `{ "passage_id", "pdf_page", "excerpt" }`. PDF pages are one-based extraction metadata.

The viewer downloads private PDF bytes with a bearer token. It does not require the
original browser's IndexedDB cache.
Auth account creation remains in Supabase Auth / Next.js.
