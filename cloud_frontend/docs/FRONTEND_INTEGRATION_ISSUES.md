# Frontend integration handoff for Cursor

This file records changes made **only** on the integration branch. Cursor's
`feat/bookrag-cloud-frontend` worktree was not edited.

1. The frontend branch at `04231b1` did not yet commit `cloud_frontend/`.
   Integration copied its working files without `.env.local`, build output,
   or `node_modules`. Please commit your frontend branch when ready.
2. The private PDF viewer previously used only IndexedDB. The integration
   branch adds `BookragClient.getPdf()` and fetches the owner's PDF through the
   authenticated FastAPI route. Keep this path when syncing changes.
3. Backend evidence status includes `unverified`. The frontend type guard now
   accepts it.
4. The `npm run lint` script used `next lint`; integration changed it to
   `eslint src` for Next.js 15. TypeScript test typing was also corrected.
5. The PDF worker now uses the bundled `pdfjs-dist` file, avoiding a runtime
   request to unpkg.
6. The integration-only login switch is explicitly labeled and disabled for
   production builds. Live deployments still require Supabase Auth credentials.
7. A transient network error on document load could remain visible after a
   successful retry. Integration clears it when the document loads.

Please review these as proposed frontend fixes; do not overwrite your worktree
with this snapshot without comparing your newer changes.
