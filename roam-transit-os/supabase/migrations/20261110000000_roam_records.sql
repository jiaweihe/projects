-- Roam Transit OS: operational records (riders, trips, events, incidents, complaints, invoices).
-- Apply with `supabase db push` (Supabase CLI) or paste into the Supabase SQL editor.
--
-- The Roam API connects with the database connection string (DATABASE_URL, postgres role),
-- which is not subject to these policies. Row-level security is enabled with NO policies for
-- the `anon` and `authenticated` roles, so the public Supabase REST/JS keys can read nothing.
-- Add tenant-scoped policies only if a front end ever queries Supabase directly.

create table if not exists public.roam_records (
  kind       text        not null,              -- TripRequest, Rider, Event, ...
  id         text        not null,
  tenant_id  text        not null,
  data       jsonb       not null,
  updated_at timestamptz not null default now(),
  primary key (kind, id)
);

create index if not exists roam_records_tenant_kind on public.roam_records (tenant_id, kind);

alter table public.roam_records enable row level security;
revoke all on public.roam_records from anon, authenticated;
