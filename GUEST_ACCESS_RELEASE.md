# BookRAG guest access

## How it works

The landing, sign-in, and sign-up pages offer **Continue as guest**. That action asks Supabase Auth to create an anonymous user. Supabase returns a real user ID and access token. The existing FastAPI authentication and document-ownership checks use that ID, so a guest gets a private library, the same upload and question limits, and the normal PDF and answer features.

The session is retained by Supabase in this browser and refreshed normally. BookRAG sets no guest expiration or automatic deletion. Signing out, clearing site data, or using another browser or device loses access to this guest identity and its documents. The application warns before guest sign-out. Account recovery or conversion is not included in this release.

## Production prerequisites

1. Confirm the existing Supabase project and its rate limits and cost controls. Per-user upload, question, and estimated-cost limits can be reset by creating another anonymous identity, so they are not a global abuse limit.
2. Enable **Anonymous sign-ins** in Supabase Auth for the BookRAG project. The current live setting is disabled. This is a security-sensitive access change and should be approved immediately before enabling it.
3. Deploy the reviewed frontend build to Vercel. No backend change or database migration is needed.
4. Check the live site in a fresh browser session: guest entry, upload, answer, citation view, library return, sign-out warning, and isolation from a separate guest. Avoid using a real private PDF for a disposable test identity.

## Rollback

Redeploy the previous frontend to remove guest entry points, then disable anonymous sign-ins in Supabase Auth. Existing guest data is not deleted by either step. Already signed-in guest sessions may remain valid until they expire or sign out; if immediate blocking is required, revoke those sessions separately after reviewing the impact.
