-- Apply after 001_initial.sql. Each hosted embedding batch is durable before
-- request delivery. An interrupted pending request must be reviewed manually.
alter table public.ingestion_jobs drop constraint if exists ingestion_jobs_status_check;
alter table public.ingestion_jobs add constraint ingestion_jobs_status_check
  check (status in ('queued','running','done','failed','attention'));
alter table public.ingestion_jobs add column if not exists claim_token uuid;

create table if not exists public.embedding_batches (
  document_id uuid not null references public.documents(id) on delete cascade,
  batch_index integer not null check (batch_index >= 0),
  input_sha256 text not null,
  status text not null check (status in ('pending','complete')),
  claim_token uuid not null,
  vectors jsonb,
  provider_tokens integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key(document_id, batch_index),
  check ((status='pending' and vectors is null) or (status='complete' and vectors is not null))
);
create index if not exists embedding_batches_pending_idx on public.embedding_batches(document_id) where status='pending';
alter table public.embedding_batches enable row level security;
revoke all on public.embedding_batches from anon, authenticated;
