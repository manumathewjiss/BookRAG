-- Run once in Supabase SQL editor or psql. Storage bucket must be private.
create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  filename text not null,
  storage_path text not null unique,
  sha256 text not null,
  status text not null default 'queued' check (status in ('queued','processing','ready','failed','deleted')),
  page_count integer not null default 0,
  passage_count integer not null default 0,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists documents_owner_created_idx on public.documents(owner_id, created_at desc);

create table if not exists public.passages (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  chunk_index integer not null,
  pdf_page integer not null check (pdf_page > 0),
  text text not null,
  embedding vector(1024) not null,
  unique(document_id, chunk_index)
);
create index if not exists passages_document_idx on public.passages(document_id);
-- The initial release uses exact benchmark BM25 in Python, not Postgres FTS.
-- pgvector exact search is used for correctness; add an ANN index only after evaluation.

create table if not exists public.ingestion_jobs (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null unique references public.documents(id) on delete cascade,
  status text not null default 'queued' check (status in ('queued','running','done','failed')),
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  lease_until timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists ingestion_jobs_claim_idx on public.ingestion_jobs(status, available_at);

create table if not exists public.usage_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  document_id uuid references public.documents(id) on delete set null,
  operation text not null check (operation in ('upload','question','embedding')),
  provider text,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  estimated_usd numeric(12,6) not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists usage_owner_day_idx on public.usage_events(owner_id, created_at desc);

alter table public.documents enable row level security;
alter table public.passages enable row level security;
alter table public.usage_events enable row level security;
alter table public.ingestion_jobs enable row level security;

create policy documents_owner_select on public.documents for select to authenticated using (owner_id = (select auth.uid()) and status <> 'deleted');
create policy passages_owner_select on public.passages for select to authenticated using (owner_id = (select auth.uid()));
create policy usage_owner_select on public.usage_events for select to authenticated using (owner_id = (select auth.uid()));
-- No client insert/update/delete policy. The backend uses a private DB credential and
-- explicitly filters every document/passages query by owner_id.
revoke all on public.ingestion_jobs from anon, authenticated;

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('bookrag-pdfs', 'bookrag-pdfs', false, 26214400, array['application/pdf'])
on conflict (id) do update set public = false;
-- No browser storage policy: only backend service role may read/write source PDFs.
