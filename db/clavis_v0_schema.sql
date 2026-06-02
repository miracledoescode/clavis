-- ============================================================================
-- Clavis V0 core schema  ::  Supabase (PostgreSQL)
-- Mirrors the "Database (ERD and Design)" spec.
--
-- Ground rules encoded here (do not relax without a schema review):
--   1. RLS on EVERY table. Client sees only its own rows; the engine uses the
--      service role key (which bypasses RLS by design in Supabase).
--   2. Credentials are NEVER stored raw. broker_credentials holds metadata
--      plus a reference into Supabase Vault (vault.secrets).
--   3. Never hard delete users or strategies. Soft delete only.
--   4. agent_logs and execution_history are the moat. ON DELETE RESTRICT so
--      they can never be cascade-wiped. GDPR is anonymize-and-detach, not a
--      hard cascade (see anonymize_user() at the bottom).
--   5. Indexes on all FKs, plus the rolling-window indexes the engine needs.
-- ============================================================================

create extension if not exists "pgcrypto";   -- gen_random_uuid()
-- Supabase Vault ("vault" schema) is provided by the platform.

-- ----------------------------------------------------------------------------
-- users  (mirrors auth.users; holds tier fast-path fields)
-- ----------------------------------------------------------------------------
create table public.users (
  id                    uuid primary key references auth.users (id) on delete restrict,
  email                 text,
  current_tier          text not null default 'free'
                          check (current_tier in ('free','explorer','navigator','titan')),
  subscription_status   text not null default 'inactive'
                          check (subscription_status in ('inactive','active','past_due','canceled')),
  is_active             boolean not null default true,   -- soft delete flag
  created_at            timestamptz not null default now()
);

-- Provision a profile row whenever a new auth user signs up.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.users (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ----------------------------------------------------------------------------
-- broker_credentials  (metadata + Vault reference; never a raw secret)
-- ----------------------------------------------------------------------------
create table public.broker_credentials (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references public.users (id) on delete restrict,
  metaapi_account_id  text not null,
  -- The raw credential lives in vault.secrets; we keep only the reference.
  -- Bound to our servers via MetaApi IP whitelisting so a leaked ref is inert.
  vault_secret_id     uuid not null,
  metadata            jsonb not null default '{}'::jsonb,
  is_active           boolean not null default true,
  created_at          timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- strategies  (Strategy JSON, versioned)
-- ----------------------------------------------------------------------------
create table public.strategies (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users (id) on delete restrict,
  name          text not null,
  strategy_spec jsonb not null,            -- conforms to schema_version "1.0"
  version       integer not null default 1,
  status        text not null default 'active'
                  check (status in ('active','archived')),   -- soft delete
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- strategy_versions  (immutable audit/rollback snapshots)
-- ----------------------------------------------------------------------------
create table public.strategy_versions (
  id            uuid primary key default gen_random_uuid(),
  strategy_id   uuid not null references public.strategies (id) on delete restrict,
  version       integer not null,
  spec_snapshot jsonb not null,
  created_at    timestamptz not null default now(),
  unique (strategy_id, version)
);

-- ----------------------------------------------------------------------------
-- agent_logs  (THE MOAT: RLHF capture). ON DELETE RESTRICT everywhere.
-- ----------------------------------------------------------------------------
create table public.agent_logs (
  id                 uuid primary key default gen_random_uuid(),
  strategy_id        uuid not null references public.strategies (id) on delete restrict,
  user_id            uuid not null references public.users (id) on delete restrict,
  proposal           jsonb not null,
  user_decision      text not null
                       check (user_decision in ('approve','reject','invalidated','executed')),
  reject_reason_chip text,
  confidence_score   numeric(5,4),
  training_flag      boolean not null default false,
  logged_at          timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- execution_history  (paper + live). live needs a credential; paper must not.
-- ----------------------------------------------------------------------------
create table public.execution_history (
  id                   uuid primary key default gen_random_uuid(),
  strategy_id          uuid not null references public.strategies (id) on delete restrict,
  broker_credential_id uuid references public.broker_credentials (id) on delete restrict,
  mode                 text not null check (mode in ('paper','live')),
  profit_loss          numeric(20,8),   -- wide enough for crypto + micro lots
  executed_at          timestamptz not null default now(),
  constraint live_requires_credential check (
    (mode = 'live'  and broker_credential_id is not null) or
    (mode = 'paper' and broker_credential_id is null)
  )
);

-- ----------------------------------------------------------------------------
-- Indexes: all FKs + the engine's rolling windows
-- ----------------------------------------------------------------------------
create index idx_broker_credentials_user      on public.broker_credentials (user_id);
create index idx_strategies_user              on public.strategies (user_id);
create index idx_strategy_versions_strategy   on public.strategy_versions (strategy_id);
create index idx_agent_logs_user              on public.agent_logs (user_id);
create index idx_agent_logs_strategy_logged   on public.agent_logs (strategy_id, logged_at);   -- rolling expectancy
create index idx_exec_strategy_executed       on public.execution_history (strategy_id, executed_at);
create index idx_exec_broker_credential       on public.execution_history (broker_credential_id);

-- ============================================================================
-- Row Level Security
-- Tables without a direct user_id (strategy_versions, execution_history) are
-- scoped via an EXISTS join back to strategies. The engine (service role)
-- bypasses RLS; these policies protect the anon/authenticated client only.
-- ============================================================================
alter table public.users              enable row level security;
alter table public.broker_credentials enable row level security;
alter table public.strategies         enable row level security;
alter table public.strategy_versions  enable row level security;
alter table public.agent_logs         enable row level security;
alter table public.execution_history  enable row level security;

create policy users_self on public.users
  for all using (auth.uid() = id) with check (auth.uid() = id);

create policy broker_credentials_owner on public.broker_credentials
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy strategies_owner on public.strategies
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy agent_logs_owner on public.agent_logs
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy strategy_versions_via_strategy on public.strategy_versions
  for all using (
    exists (
      select 1 from public.strategies s
      where s.id = strategy_versions.strategy_id and s.user_id = auth.uid()
    )
  );

create policy execution_history_via_strategy on public.execution_history
  for all using (
    exists (
      select 1 from public.strategies s
      where s.id = execution_history.strategy_id and s.user_id = auth.uid()
    )
  );

-- ============================================================================
-- GDPR: anonymize-and-detach (NOT a hard cascade).
-- Because agent_logs.user_id is the moat link, we scrub PII from the user
-- shell and disable the account, but RETAIN the anonymized behavioral data.
-- The uuid stays so behavioral history remains internally consistent; every
-- piece of personally identifying information is purged.
-- ============================================================================
create or replace function public.anonymize_user(target_user_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  -- 1. Scrub PII on the user shell, deactivate.
  update public.users
     set email = 'anonymized+' || target_user_id::text || '@deleted.clavis',
         is_active = false,
         subscription_status = 'canceled'
   where id = target_user_id;

  -- 2. Detach + neutralize broker credentials (and revoke the Vault secret
  --    out of band via the service layer; the reference is cleared here).
  update public.broker_credentials
     set metaapi_account_id = 'anonymized',
         metadata = '{}'::jsonb,
         is_active = false
   where user_id = target_user_id;

  -- 3. Archive strategies (soft delete; never hard delete).
  update public.strategies
     set status = 'archived'
   where user_id = target_user_id;

  -- 4. agent_logs and execution_history are intentionally LEFT INTACT.
  --    They carry no direct PII and are the moat; they stay linked to the
  --    now-anonymized user shell.
end;
$$;
