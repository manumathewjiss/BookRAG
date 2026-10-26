-- Apply after 001 and 002. Keep browser users read-only; the backend owns writes.
-- An owner mismatch between a passage and its document must fail at the database.
create unique index if not exists documents_id_owner_idx on public.documents(id, owner_id);
alter table public.passages drop constraint if exists passages_document_owner_fk;
alter table public.passages add constraint passages_document_owner_fk
  foreign key (document_id, owner_id) references public.documents(id, owner_id) on delete cascade;

revoke all on public.documents, public.passages, public.usage_events,
  public.ingestion_jobs, public.embedding_batches from anon, authenticated;
grant select on public.documents, public.passages, public.usage_events to authenticated;

-- Storage is private and accepts only PDFs within the application upload limit.
update storage.buckets set public = false, file_size_limit = 26214400,
  allowed_mime_types = array['application/pdf']
where id = 'bookrag-pdfs';
