-- Public sky map, candidates and votes.
-- Run once in the Supabase SQL editor.

-- --- Tables ---

create table public.sky_searches (
  id          bigint generated always as identity primary key,
  created_at  timestamptz not null default now(),
  field_id    text not null,
  ra_center   real not null,   -- rounded to a coarse patch, never an exact location
  dec_center  real not null,
  source      text not null check (source in ('overhead', 'manual'))
);

create table public.candidates (
  id          bigint generated always as identity primary key,
  created_at  timestamptz not null default now(),
  ra          double precision not null,
  dec         double precision not null,
  pm_ra       real,             -- arcsec per year
  pm_dec      real,
  rate        real,             -- arcsec per hour, for fast movers
  frames_used integer,
  checks      jsonb,
  status      text not null default 'passed_checks' check (status in (
                'flagged', 'passed_checks', 'community_confirmed',
                'team_reviewed', 'known', 'artifact', 'unexplained'))
);

create table public.votes (
  id           bigint generated always as identity primary key,
  created_at   timestamptz not null default now(),
  candidate_id bigint not null references public.candidates (id) on delete cascade,
  device_id    uuid not null,   -- random id kept in the visitor's browser
  vote         text not null check (vote in ('real', 'artifact')),
  unique (candidate_id, device_id)
);

-- --- Row level security ---
-- Anyone can read. The public (anon) key can only add searches and votes.
-- Candidates are written by the back end with the service key, which bypasses RLS.
-- Status changes are made by the team in the dashboard.

alter table public.sky_searches enable row level security;
alter table public.candidates   enable row level security;
alter table public.votes        enable row level security;

create policy "read searches"  on public.sky_searches for select to anon, authenticated using (true);
create policy "add searches"   on public.sky_searches for insert to anon, authenticated with check (true);

create policy "read candidates" on public.candidates for select to anon, authenticated using (true);

create policy "read votes"     on public.votes for select to anon, authenticated using (true);
create policy "add votes"      on public.votes for insert to anon, authenticated with check (true);

-- --- Vote counts ---

create view public.candidate_votes with (security_invoker = true) as
select
  candidate_id,
  count(*) filter (where vote = 'real')     as real_votes,
  count(*) filter (where vote = 'artifact') as artifact_votes
from public.votes
group by candidate_id;
