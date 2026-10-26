# BookRAG cloud verification runbook

This branch prepares a **separate test environment**. Nothing in this runbook has
been deployed or called against a hosted model yet. Keep the integration commit
`5c2e63c` and the research benchmark files unchanged.

## What is ready

The FastAPI web process and the separate ingestion worker use the same code but
different commands. The worker downloads a private PDF, extracts text per PDF
page, makes up to 450-token passages with a 50-token overlap, embeds batches of
32, then publishes all passages together. Passage numbers are one-based PDF page
numbers from the parser. This is close to the research splitter's 450/50 setting,
but it deliberately never spans a PDF page boundary. It has not yet been proven
equivalent on arbitrary new PDFs.

The saved embedding batches are durable. A completed batch is reused after a
restart. If a request may have reached Voyage but its result was lost, the batch
and job require operator attention; the worker does not send it again blindly.
A definite provider rejection releases the batch for a later attempt. The API
enforces per-user upload, question, minute, and estimated daily spending limits.
These are application estimates, **not provider billing hard stops**.

## 1. Create an isolated Supabase test project

1. In [Supabase](https://supabase.com/dashboard), create a **new test project**.
   Do not point this code at the local BookRAG database or an existing project
   with user documents. Check its plan and region before confirming any paid plan.
2. In SQL Editor, apply these files in order, once:
   `migrations/001_initial.sql`, `migrations/002_embedding_checkpoints.sql`,
   `migrations/003_cloud_readiness.sql`. The first adds pgvector, tables, owner
   policies, and the private `bookrag-pdfs` bucket. The third restricts browser
   table grants and prevents a passage from claiming another document's owner.
3. In Auth settings, enable email/password sign-in for a controlled test. Create
   **two distinct test users** and obtain short-lived access tokens through the
   normal sign-in flow. Never put these tokens in Git or chat.
4. Keep `bookrag-pdfs` **private**. Do not create broad `storage.objects`
   read/write policies. Only the backend uses the server-side service role key.
   The browser reads PDFs through `GET /api/v1/documents/{id}/pdf`, which first
   validates the user's token and ownership. Treat the service role key and the
   Postgres connection URL as secrets.
5. Get the direct Postgres connection string, or the session pooler if the host
   cannot reach the direct IPv6 address. Include `sslmode=require`. The
   transaction pooler is not the default choice for this persistent Python
   service. Use the direct connection for migrations.
6. With credentials only in a local ignored `.env`, run the read-only check:

   ```bash
   cd cloud_backend
   python -m scripts.supabase_preflight --execute
   ```

   It checks pgvector dimension, row-level security, owner policies, table
   grants, the private PDF bucket, and storage policy count. Resolve every failed
   item before the real smoke test. A project with other storage policies needs
   manual policy review.

Supabase references: [database connections](https://supabase.com/docs/guides/database/connecting-to-postgres),
[row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security),
[private storage access](https://supabase.com/docs/guides/storage/security/access-control).

## 2. Configure secrets without exposing them

Copy `.env.example` to `.env` **inside `cloud_backend/`** and set the values
locally. `.env` is ignored by Git. Do not paste values into terminal commands,
issue descriptions, screenshots, test reports, or chat.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | API + worker | Test Supabase Postgres with TLS |
| `SUPABASE_URL` | API + worker | Test project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | API + worker | Server-only Auth check and private PDF Storage |
| `SUPABASE_STORAGE_BUCKET` | API + worker | `bookrag-pdfs` |
| `VOYAGE_API_KEY` | API + worker | `voyage-4-large` and `rerank-3` |
| `OPENAI_API_KEY` | API only | `gpt-6.1-sol` answer generation |
| `ALLOWED_ORIGINS` | API | Exact frontend origin(s), comma-separated |
| `MAX_PDF_BYTES`, `MAX_PDF_PAGES`, `MAX_PASSAGES` | API/worker | Upload and extraction limits |
| `DAILY_UPLOAD_LIMIT`, `DAILY_QUESTION_LIMIT`, `QUESTIONS_PER_MINUTE_LIMIT`, `DAILY_ESTIMATED_USD_LIMIT`, `QUESTION_RESERVE_USD` | API | User usage guards |

For the **local real-service smoke only**, set
`BOOKRAG_SMOKE_USER_A_TOKEN` and `BOOKRAG_SMOKE_USER_B_TOKEN` in the process
environment, not in Render. The two access tokens must belong to different users
in the test project. The script reports only IDs, counts, and synthetic test
content; it never prints the tokens or keys.

To obtain those sessions without typing a password into chat or a shell command,
run this from a private interactive terminal in `cloud_backend/`:

```bash
.venv/bin/python -m scripts.prepare_smoke_sessions
```

Enter each existing test user's email and password at the prompts. Passwords
are hidden. The helper signs in through Supabase Auth, checks both access tokens
through `/auth/v1/user`, requires distinct user IDs, and saves only the access
tokens to ignored `verification_sessions.env` with mode 600. No refresh tokens
or passwords are stored. Access tokens expire, so repeat this step if the live
test happens later. After separate approval for the live test, load the tokens
in the same terminal with `source verification_sessions.env` before running the
smoke command. Never paste the file contents into chat, logs, or Git.

## 3. Real-service smoke, separately approved

The script is safe by default:

```bash
cd cloud_backend
python -m scripts.supabase_preflight
python -m scripts.cloud_smoke
```

Those two commands are offline dry runs. The smoke manifest contains the exact
synthetic two-page PDF hash. **Do not create the approval file or use `--execute`
until the user separately approves the live verification.** After that approval,
create ignored `verification_approval.json` with these exact fields and the hash
printed by the dry run:

```json
{
  "approved": true,
  "pdf_sha256": "<hash from dry run>",
  "max_voyage_requests": 5,
  "max_openai_requests": 2,
  "max_voyage_usd": 0.02,
  "max_openai_usd": 0.10
}
```

Then, only for the approved test:

```bash
python -m scripts.cloud_smoke --execute --approval-file verification_approval.json
```

The test refuses to start if the new project's document/job tables are not
empty. It uploads a small synthetic two-page PDF, checks the original PDF bytes
and page-2 chunk, tests both users through the API and database RLS, runs one
ingestion job, asks one answerable and one unanswerable question, validates the
page-2 citation and refusal, and deletes the document. Any incomplete run is
marked `attention` in ignored `verification_runs/` and cannot be started again
automatically. Review the provider usage and any uploaded test document before
deciding whether to make a new attempt. The script makes **at most 5 Voyage
requests and 2 OpenAI requests**, without automatic retries. The conservative
runner reserves up to $0.02 and $0.10 respectively; it stops before a call that
would exceed either cap. Provider billing pages remain the source of truth.

At current published list rates, a two-passage synthetic PDF should cost far
less than these caps. Voyage lists $0.12 per million embedding tokens and $0.05
per million processed rerank tokens; the account may have free allowance.
OpenAI lists GPT-6.1 Sol Standard input at $2 and output at $10 per million
tokens. The guard assumes twice the local input estimate and reserves the full
1024-token output limit per answer. Stop if a model is inaccessible, provider
usage cannot be bounded, a hash differs, an auth/RLS check fails, or a pending
embedding batch needs review.

Pricing references: [Voyage](https://docs.voyageai.com/docs/pricing),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

## 4. Render deployment, only after separate approval

`render.yaml` describes one Docker web service and one Docker worker, both
`starter` plan and `autoDeploy: false`. Creating them may create paid services.
No Render resources have been created in this sprint.

1. Connect the repository and select `cloud_backend/render.yaml` as the Blueprint
   path. Validate the Blueprint before applying it. The Docker image starts the
   API on Render's `PORT` and the worker with `python -m bookrag_cloud.worker`.
2. Set the secret environment variables above in Render for the services that
   need them. Set `ALLOWED_ORIGINS` to the exact Vercel frontend URL. Do not use
   a wildcard or put service keys in Next.js public variables.
3. Deploy web and worker only after the Supabase preflight and small local
   real-service smoke pass. Check `/api/v1/health`, then sign in and test upload,
   processing status, answer, citation PDF page, private PDF view, and deletion.
4. With two browser users, confirm one cannot list, open, chat with, or delete
   the other's document. Check the worker logs for completed jobs and no
   unreviewed `attention` batches. Then check provider dashboards and Render
   usage. Stop the services if costs or behavior depart from the small test.

Render references: [Blueprint specification](https://render.com/docs/blueprint-spec),
[background workers](https://render.com/docs/background-workers),
[environment variables](https://render.com/docs/configure-environment-variables),
[health checks](https://render.com/docs/health-checks).

## Known verification boundary

Offline tests cover application behavior with mocks. They cannot prove actual
Supabase grants, network reachability, provider model access, or a deployed
Render/Vercel path. The local live smoke will prove those services for a tiny
synthetic PDF only. A larger professor PDF and realistic concurrency test should
be approved separately after this small test succeeds.
