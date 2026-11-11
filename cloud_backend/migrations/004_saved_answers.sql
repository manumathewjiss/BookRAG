-- Apply after 003_cloud_readiness.sql. Do not run automatically from the app.
-- Order: 001_initial → 002_embedding_checkpoints → 003_cloud_readiness → 004_saved_answers.
-- Saved answers are scoped to one user and one document. Deleting a document
-- removes its rows before Storage deletion (documents are soft-deleted).

create table if not exists public.saved_answers (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  document_id uuid not null,
  question_original text not null,
  question_canonical text not null,
  question_signature jsonb not null,
  answer_text text not null,
  enough_evidence boolean not null,
  evidence_status text not null,
  citations jsonb not null,
  document_sha256 text not null,
  pipeline_version text not null,
  created_at timestamptz not null default now(),
  constraint saved_answers_document_owner_fk foreign key (document_id, owner_id)
    references public.documents(id, owner_id) on delete cascade,
  unique (owner_id, document_id, question_canonical, document_sha256, pipeline_version)
);

create index if not exists saved_answers_lookup_idx
  on public.saved_answers (owner_id, document_id, document_sha256, pipeline_version, created_at desc);

alter table public.saved_answers enable row level security;
revoke all on public.saved_answers from public, anon, authenticated;
-- Backend uses a private DB credential and always filters by owner_id.
