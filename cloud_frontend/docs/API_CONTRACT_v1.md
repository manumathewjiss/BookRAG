# BookRAG Cloud API v1 (frontend snapshot)

Canonical file lives on the Codex branch at
`/Users/manumathewjiss/Documents/Codex/bookrag-cloud-backend/cloud_backend/API_CONTRACT_v1.md`.
This copy is for the sparse frontend worktree. If they diverge, Codex's file wins.

Base path: `/api/v1`. JSON uses UTF-8. All protected routes require
`Authorization: Bearer <Supabase access token>`. The backend validates that token
with Supabase Auth; it never accepts a user ID from the browser.

## Common errors

`{ "error": { "code": "short_machine_code", "message": "Safe user-facing text" } }`.

HTTP 400 invalid input, 401 missing/invalid token, 404 another
user's or nonexistent document, 409 still processing, 413 oversized PDF, 429 usage
limits, 503 provider unavailable. Disallowed origins are blocked by CORS, not a 403 body.

## Routes

| Method and path | Request | Response |
| --- | --- | --- |
| `GET /api/v1/health` | none | `{ "status": "ok" }` |
| `GET /api/v1/me` | Bearer token | `{ "user_id": "uuid", "daily_questions_used": 0, "daily_uploads_used": 0 }` |
| `POST /api/v1/documents` | `multipart/form-data`, field `file` (PDF), optional `title` | 202 `{ "document": Document }` |
| `GET /api/v1/documents` | Bearer token | `{ "documents": [Document] }` |
| `GET /api/v1/documents/{document_id}` | Bearer token | `{ "document": Document }` |
| `GET /api/v1/documents/{document_id}/pdf` | Bearer token | PDF bytes, `Content-Type: application/pdf`, `Cache-Control: private, no-store` |
| `DELETE /api/v1/documents/{document_id}` | Bearer token | 204 on deletion; 404 if already gone or not this user's |
| `POST /api/v1/documents/{document_id}/chat` | `{ "question": "8–1200 characters" }` | 200 `Answer` |

`Document`: `{ "id", "title", "filename", "status": "queued|processing|ready|failed", "page_count", "passage_count", "error", "created_at", "updated_at" }`.

`Answer`: `{ "answer", "enough_evidence", "evidence_status": "direct_answer|nearby_only|absent|unverified", "citations": [Citation], "timings_ms", "usage" }`.

`unverified` means Sol claimed support but returned no valid passage citation; the
frontend withholds that answer.

`Citation`: `{ "passage_id", "pdf_page", "excerpt" }`. PDF pages are one-based extraction metadata.

**Contract gap:** Codex's current backend `API_CONTRACT_v1.md` still says private PDF
downloads are not exposed in v1, even though integration commit `5c2e63c` added
authenticated PDF viewing in the frontend. This frontend calls
`GET /api/v1/documents/{id}/pdf`. Codex needs to keep or restore that route for
production viewing.
