# BookRAG ready sample for guest visitors

## Status

Implemented locally behind `GUEST_SAMPLE_DOCUMENT_ID` and `GUEST_SAMPLE_SHA256`; **disabled by default**. No PDF has been uploaded or shared by this change. No production configuration, database, or deployment has been changed.

The repository's `books/sample_pdfs/README.md` explicitly says `Bhagavad-gita_As_It_Is.pdf` is a copyrighted evaluation copy kept off Git. The exact 4.1 MB file is present in the older local `Pramod Gupta Project/books/sample_pdfs/` and `Projects/BookRAG/research/books/sample_pdfs/` folders; both copies have SHA-256 `d90b9ab35534421205cf396e1262fcc8ce3a1a2467233e1c89ab7e9cddc9ae4f`. It is absent from the BookRAG Git checkout's sample folder. Do not make it a public guest sample without confirming permission to distribute that edition. Use a shareable Gita edition if permission is unavailable.

## How it works

An operator uploads an approved PDF once through the normal BookRAG account and waits until it is ready. The backend is then configured with that ready document's UUID. Every authenticated visitor, including a guest, sees the document marked **Sample** and can ask questions. The full PDF endpoint returns 403 for visitors. After an answer cites a passage, the visitor can open only that cited page as a one-page PDF. Random passage IDs return 404. The sample remains owned by its original uploader; another visitor cannot remove it. Other private documents remain owner-scoped and return 404 to other users.

**Viewing is not copy protection.** The browser receives that one-page PDF and can save or screenshot it. This design prevents a visitor from requesting the full source PDF through BookRAG, but it cannot guarantee that displayed pages are impossible to copy. Sharing even single pages may require permission; do not activate an edition without an appropriate right to show those pages to all guests.

The source passages and vectors are reused at question time, so the PDF is not re-indexed per guest. Exact saved answers for this public sample are shared under the sample owner's cache key because migration `004` requires saved-answer ownership to match document ownership. Guest chat history stays in each guest's browser storage; it is not a cross-guest question feed. Any visitor who asks precisely the same question may receive the same stored answer and citations. New questions still call Voyage and OpenAI and count toward that visitor's limit.

For new sample questions, `GUEST_SAMPLE_DAILY_USD_LIMIT` is a shared daily estimated-cost guard across all users. Its default is `0`, blocking new paid sample questions until an operator explicitly sets a budget. Cached exact-answer hits remain available at zero provider cost. This is an application estimate, not a billing-platform hard cap; monitor provider accounts separately. Guests can create new identities, so ordinary per-user limits alone are insufficient.

## Activation after rights and source are resolved

1. Confirm redistribution rights for the exact PDF, or choose a shareable edition. Record the source and license.
2. Upload that PDF to a dedicated sample-owner account. Verify `ready`, page count, passage count, citations, and PDF viewing. Preserve its document UUID and SHA-256 digest.
3. Set `GUEST_SAMPLE_DOCUMENT_ID` to that UUID, `GUEST_SAMPLE_SHA256` to its digest, and `GUEST_SAMPLE_DAILY_USD_LIMIT` to an explicit small daily estimate, then deploy the reviewed backend and frontend. This feature needs no database migration. A missing or mismatched digest keeps the sample hidden.
4. In a fresh guest session, verify the sample appears ready immediately, a new question succeeds, an exact repeat is reused, and the PDF viewer opens only the cited page. Confirm the full PDF endpoint returns 403, an unknown passage ID returns 404, and the returned PDF has exactly one page. Check another guest sees the sample but not the first guest's personal PDF. Confirm a guest receives 404 trying to delete the sample or another user's document.
5. Review usage and provider billing before increasing the shared budget.

## Disable or rollback

Clear `GUEST_SAMPLE_DOCUMENT_ID` to hide the sample from visitors. Do not delete the source document or its passages. Redeploy the previous API and frontend if a code rollback is needed. Existing private document data stays intact.
