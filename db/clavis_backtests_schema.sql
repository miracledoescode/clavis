-- ============================================================================
-- Clavis backtests schema  ::  Supabase (PostgreSQL)
-- A backtest run + its report card, owned by the trader. RLS owner-only, same
-- pattern as strategies. The engine loads the owner's strategy and writes the
-- result under the authenticated (RLS-scoped) context — never the service role.
-- ============================================================================

create table public.backtests (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references public.users (id) on delete restrict,
  strategy_id       uuid not null references public.strategies (id) on delete restrict,
  strategy_version  integer,
  status            text not null default 'queued'
                      check (status in ('queued','running','done','error')),
  params            jsonb not null default '{}'::jsonb,   -- window, costs, etc.
  report            jsonb,                                 -- the report card payload
  error             text,
  created_at        timestamptz not null default now(),
  completed_at      timestamptz
);

create index idx_backtests_user     on public.backtests (user_id);
create index idx_backtests_strategy on public.backtests (strategy_id);

alter table public.backtests enable row level security;

create policy backtests_owner on public.backtests
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
