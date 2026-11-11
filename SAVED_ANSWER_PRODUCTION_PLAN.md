# Saved Answers: production release and rollback plan

**State on 2026-11-05:** local changes and tests only. No production backup, migration, deployment, live model request, or user-data change has been performed. This is the approval checkpoint.

## Local reliability review

1. **Simultaneous requests:** the API takes a PostgreSQL session advisory lock keyed by owner and document before its second ownership check, cache lookup, and any hosted call. A second equivalent request waits, reads the first saved answer, and should make zero hosted calls. A 60-second wait returns HTTP 503 instead of starting a duplicate paid request. Connection loss releases the lock. Deletion uses the same lock, so a waiting chat rechecks whether the document still exists. This also serializes unrelated questions for one PDF; a long answer can make another request wait or return 503.
2. **Cache write failure:** paid usage is settled before the optional saved-answer write. A database driver failure on that write is logged without private question/answer content; the freshly generated answer and citations still return. That response is not guaranteed reusable because it was not saved.
3. **Deletion failure:** cache rows are removed before PDF Storage bytes. If the cache purge fails, deletion stops while the document and PDF remain. If Storage deletion then fails, the document remains but cached answers may already be removed; they can be regenerated. Storage and PostgreSQL are separate systems, so a later database failure after Storage deletion remains a residual risk. Do not claim fully atomic deletion.
4. **Migration safety:** Production already has `004_saved_answers.sql`. This release does not reapply it and does not ship a later migration. Preflight confirms `public.saved_answers` exists, with the unique key `(owner_id, document_id, question_canonical, document_sha256, pipeline_version)`, the lookup index, row-level security, and no privileges for `anon` or `authenticated`. Columns stop at `created_at`. `question_embedding`, `match_policy_version`, `cost_breakdown`, and `cost_certainty` must be absent. If the table is missing or those extra columns are present, stop. Do not execute SQL to repair it during this release.

**Local checks:** recorded against the release commit in the review packet. Added tests cover an exact repeat with identical answer text and citations, zero hosted calls on that hit, a changed question running retrieval, the required negative pairs, cross-user and cross-document isolation, digest and pipeline invalidation, usage settlement, cache-write failure, deletion, and concurrent identical requests producing one paid answer. PostgreSQL checks use a local database with migrations 001–004 only.

## Approval and cost boundary

The live verification proposes **at most two new questions** on one existing ready PDF owned by the tester: one answerable question, then one question that changes a word that can change the fact (for example “is” versus “was”). The first question may cause one Voyage query embedding, one Voyage rerank, and one OpenAI answer call. Repeating that same question, including differences limited to surrounding whitespace, one trailing question mark, or apostrophe glyphs, must return the identical answer text and citations with `reused_answer=true` and **zero** new Voyage or OpenAI calls. The changed question runs the normal retrieval pipeline and may cause a second paid call. User-isolation rejection and read-only schema checks cause **zero** paid calls. No upload, ingestion, or document deletion is part of this smoke.

**Proposed paid-test ceiling: US$0.25 in provider charges, with at most two new answer pipelines (two embeddings, two reranks, two generations).** This is an approval limit, not a hard technical billing cap: provider usage may differ from application estimates, and the application has no per-test provider spending switch. Check provider usage before and after; stop after the approved number of new questions or if observed usage approaches $0.25. If an exact hard cap is required, defer the live paid test until provider-side limits are confirmed. Existing hosting services may continue normal recurring charges; this plan creates no new service.

Approval is required separately for production backup/migration/deploy and for the bounded paid live test. Never print credentials, tokens, passwords, or private PDF text in reports.

## Exact production sequence after approval

1. **Freeze and record:** identify the Supabase project, Render API service, Vercel project, production branch, current deployment IDs/commits, and intended release commit. Confirm Render `bookrag-api` and `bookrag-ingestion` are the existing services with `autoDeploy: false`; confirm Vercel production-branch/auto-deploy settings before pushing. Exclude unrelated `ui_references/` and research documents from the release commit. The worker needs no deployment for this feature.
2. **Read-only preflight:** verify migrations 001, 002, 003, and 004 are already applied; `documents_id_owner_idx` exists; `public.saved_answers` is present with the columns and unique key from `004_saved_answers.sql`; `question_embedding`, `match_policy_version`, `cost_breakdown`, and `cost_certainty` are absent. Capture counts of `documents` by status, `passages`, `ingestion_jobs`, `embedding_batches`, `usage_events`, `saved_answers`, and private-bucket objects. Record only counts and IDs needed for testing. If `saved_answers` is missing, stop. Do not apply `004` as part of this release.
3. **Backup:** create a fresh PostgreSQL custom-format logical backup with a compatible `pg_dump` version to a private location outside Git before deploying code. Use the Supabase-provided database connection through a secure environment mechanism, not in shell history or logs. Command template: `pg_dump --format=custom --no-owner --no-acl --file=<private-path>/bookrag-pre-strict-v1.dump <database-connection>`. Validate with `pg_restore --list <private-path>/bookrag-pre-strict-v1.dump`, record size/checksum, and verify BookRAG tables, including `saved_answers`, are present. Confirm retention/location. Database dumps do not contain private PDF Storage object bytes. If backup cannot be produced and inspected, stop.
4. **Schema check, no migration:** run the read-only checks below. Do not execute `004_saved_answers.sql` and do not apply any later file. Recheck existing-table and Storage-object counts; stop on unexplained changes.

```sql
select column_name
from information_schema.columns
where table_schema = 'public' and table_name = 'saved_answers'
order by ordinal_position;

select indexdef
from pg_indexes
where schemaname = 'public' and tablename = 'saved_answers';

select c.relrowsecurity
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname = 'saved_answers';
```

Expected columns, in order: `id`, `owner_id`, `document_id`, `question_original`, `question_canonical`, `question_signature`, `answer_text`, `enough_evidence`, `evidence_status`, `citations`, `document_sha256`, `pipeline_version`, `created_at`. Expected unique index: `(owner_id, document_id, question_canonical, document_sha256, pipeline_version)`. `relrowsecurity` must be true.
5. **Backend:** deploy only the approved release commit to existing Render `bookrag-api` using Manual Deploy → Deploy a specific commit. Keep environment variables and service plan unchanged. Check `/api/v1/health`, authenticated `/api/v1/me`, library list, and an existing private PDF view. Inspect logs for SQL errors/5xx. These checks make no model calls.
6. **Frontend:** deploy/promote the matching frontend release to the existing Vercel project rooted at `cloud_frontend`. Confirm `bookrag.vercel.app` and API target. Check login/session restoration, library, PDF viewer, and Ask navigation. No upload, delete, or paid question yet.
7. **Approved live test:** with User A and an existing ready test PDF, record status, digest, page/passage counts. Ask one new answerable question; record the answer text and citation passage IDs and pages privately, and confirm one Voyage embedding, one rerank, and one OpenAI answer. Ask that question again with the same words, then once more with only extra spaces or a trailing question mark. Each repeat must be HTTP 200, `reused_answer=true`, the same answer text, the same citations, zero `usage`, and no new Voyage or OpenAI request. Ask one changed question, such as swapping “is” for “was”, only if the second paid pipeline was approved; require `reused_answer=false` and a normal retrieval call. With User B, attempt User A's PDF read and question submission; require 404 and no provider call. Do not delete the PDF. Recheck status, digest, page/passage counts, and the Storage object. Do not report private answer text.
8. **Finish:** compare provider usage and application usage events. Confirm no extra calls on hits, no cross-user leakage, and no unexpected 5xx. Record deployment IDs and outcomes. If an acceptance check fails, stop and roll back.

## Rollback

- **Schema check fails:** stop. Do not apply or reapply a migration. Current deployed code remains unchanged.
- **Backend failure:** roll `bookrag-api` back to its recorded last successful Render deployment, parent commit `6ed2054737b35829175b9732d42445c6c506a578` until a newer rollback target is recorded at deploy time. That parent has no saved-answer lookup. Verify health, library, and PDF view. Rows written by this release stay in `saved_answers` and are unused by the previous API. Only run another paid chat if separately approved.
- **Frontend failure:** use Vercel Instant Rollback to the previous production deployment. The previous frontend omits the “Previously answered” badge and still renders the answer.
- **Database:** do not drop `saved_answers` and do not reverse `004`. Dropping the table deletes saved answers and needs separate approval. Full restore is only for actual corruption, must account for newer user writes, and does not restore Storage PDFs.
- **After rollback:** recheck document/passage counts, PDF availability, login, and logs. Do not automatically replay paid calls.

Official platform references: [Supabase backups](https://supabase.com/docs/guides/platform/backups), [Supabase backup/restore](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore), [Render deploys](https://render.com/docs/deploys), [Render rollbacks](https://render.com/docs/rollbacks), [Vercel promotion](https://vercel.com/docs/deployments/promoting-a-deployment), [Vercel instant rollback](https://vercel.com/docs/instant-rollback).
