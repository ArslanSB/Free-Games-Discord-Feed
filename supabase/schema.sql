-- Run once in the Supabase SQL editor when setting up the project.

create table if not exists seen_posts (
  id text primary key,
  title text not null,
  store text,
  link text,
  posted_at timestamptz not null default now()
);

create table if not exists bot_runs (
  id bigserial primary key,
  ran_at timestamptz not null default now(),
  items_seen int not null,
  items_new int not null,
  items_posted int not null,
  errors text
);

create index if not exists bot_runs_ran_at_idx on bot_runs (ran_at desc);
