-- Question-language previews are separately metered from answered questions.
alter table public.usage_events drop constraint if exists usage_events_operation_check;
alter table public.usage_events add constraint usage_events_operation_check
  check (operation in ('upload','question','embedding','question_preview'));
