-- Developer job finder schema. Shares the Supabase project with the nurse job finder; every object is
-- prefixed dev_ so the two never touch each other's data. Safe to re-run.
--
-- dev_jobs:        written only by the GitHub Action with the secret key (RLS on, no policies).
-- dev_job_status:  application tracking. Each row belongs to the login that created it, and only that
--                  login can see or change it (the nurse dashboard's users can't see these).

create table if not exists public.dev_jobs (
  id           text primary key,             -- "himalayas:...", "remotive:123", "hnwhoishiring:456"
  source       text not null,
  title        text not null,
  company      text,
  url          text,
  restriction  text,                         -- where candidates may be based, as the board states it
  location     text,
  remote       boolean,
  access       text check (access in ('worldwide', 'region', 'nigeria', 'visa', 'unclear', 'restricted', 'abroad', 'no-visa')),
  access_note  text,
  salary       text,
  usd_year     integer,                      -- approximate, for the minimum-pay rule and sorting
  job_type     text,
  posted       date,
  closes       date,
  score        integer,
  label        text check (label in ('APPLY', 'REVIEW', 'SKIP')),
  skills       text[],
  notes        text[],
  snippet      text,
  first_seen   date not null default current_date,
  last_seen    date not null default current_date,
  updated_at   timestamptz not null default now()
);
create index if not exists dev_jobs_last_seen_idx on public.dev_jobs (last_seen);
create index if not exists dev_jobs_label_idx on public.dev_jobs (label);

create table if not exists public.dev_job_status (
  owner       uuid not null default auth.uid() references auth.users (id) on delete cascade,
  job_id      text not null references public.dev_jobs (id) on delete cascade,
  status      text not null check (status in ('saved', 'applied', 'interview', 'offer', 'rejected', 'hidden')),
  note        text,
  updated_at  timestamptz not null default now(),
  primary key (owner, job_id)
);

alter table public.dev_jobs enable row level security;
alter table public.dev_job_status enable row level security;

-- Revoke Supabase's default grants first: TRUNCATE in particular bypasses row-level security.
revoke all on public.dev_jobs from anon, authenticated;
revoke all on public.dev_job_status from anon, authenticated;
grant select, insert, update, delete on public.dev_job_status to authenticated;
grant all on public.dev_jobs, public.dev_job_status to service_role;

drop policy if exists "own statuses: read" on public.dev_job_status;
drop policy if exists "own statuses: add" on public.dev_job_status;
drop policy if exists "own statuses: change" on public.dev_job_status;
drop policy if exists "own statuses: remove" on public.dev_job_status;
create policy "own statuses: read" on public.dev_job_status for select to authenticated using (owner = (select auth.uid()));
create policy "own statuses: add" on public.dev_job_status for insert to authenticated with check (owner = (select auth.uid()));
create policy "own statuses: change" on public.dev_job_status for update to authenticated
  using (owner = (select auth.uid())) with check (owner = (select auth.uid()));
create policy "own statuses: remove" on public.dev_job_status for delete to authenticated using (owner = (select auth.uid()));

create or replace function public.dev_touch_job_status() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists dev_job_status_touch on public.dev_job_status;
create trigger dev_job_status_touch before insert or update on public.dev_job_status
  for each row execute function public.dev_touch_job_status();
