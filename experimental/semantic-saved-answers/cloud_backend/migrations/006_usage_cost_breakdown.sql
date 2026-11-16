-- NOT USED by strict Saved Answers v1. Do not apply this file for that release.
-- The running API settles usage_events with the columns created in 001_initial.sql.
-- Apply after 005 only if a later design explicitly adopts it. Do not run automatically.
-- Order: … → 004_saved_answers → 005_saved_answer_question_embeddings → 006_usage_cost_breakdown.
-- Additive. Records per-call cost lines and whether the total is a known measurement
-- or still includes the pre-call reservation because a provider charge was uncertain.
-- Existing rows keep cost_certainty 'known' and an empty breakdown.

alter table public.usage_events
  add column if not exists cost_breakdown jsonb not null default '[]'::jsonb;

alter table public.usage_events
  add column if not exists cost_certainty text not null default 'known';

alter table public.usage_events
  drop constraint if exists usage_events_cost_certainty_check;

alter table public.usage_events
  add constraint usage_events_cost_certainty_check
  check (cost_certainty in ('known', 'uncertain'));
