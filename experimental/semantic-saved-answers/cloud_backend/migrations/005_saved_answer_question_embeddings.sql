-- NOT USED by strict Saved Answers v1. Do not apply this file for that release.
-- The running API does not read or write question_embedding or match_policy_version.
-- Apply after 004_saved_answers.sql only if a later design explicitly adopts it. Do not run automatically from the app.
-- Order: … → 004_saved_answers → 005_saved_answer_question_embeddings.
-- Additive only: safe if 004 is already applied; if neither is applied, run 004 then 005.
-- question_embedding enables pgvector candidate recall for semantic reuse.
-- match_policy_version records which matching/verifier policy wrote the row.
-- Rows with a null embedding, or with match_policy_version other than the
-- running policy, stay available for exact and rule reuse only. They are not
-- semantic candidates. Do not backfill embeddings with a paid job from this
-- migration. The next full answer for a new wording stores a fresh vector.

alter table public.saved_answers
  add column if not exists question_embedding vector(1024);

alter table public.saved_answers
  add column if not exists match_policy_version text not null default 'rules-v1';

-- Per-document candidate lists are small; filter index + exact <=> order is enough.
-- Do not authorize reuse from distance alone — the application always runs a verifier.
create index if not exists saved_answers_semantic_lookup_idx
  on public.saved_answers (owner_id, document_id, document_sha256, pipeline_version)
  where question_embedding is not null;
