-- ============================================================================
-- Clavis billing schema  ::  Supabase (PostgreSQL)
-- subscriptions + billing_events. Provider is Dodo Payments (Merchant of
-- Record) because Stripe does not onboard Nigeria-based businesses.
--
-- The idempotency ledger is load-bearing: Dodo webhooks follow the Standard
-- Webhooks spec and can be redelivered. billing_events.idempotency_key is
-- UNIQUE so a replayed webhook is a no-op, never a double charge of state.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- subscriptions
-- ----------------------------------------------------------------------------
create table public.subscriptions (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references public.users (id) on delete restrict,
  tier                  text not null
                          check (tier in ('explorer','navigator','titan')),
  status                text not null default 'active'
                          check (status in ('active','past_due','canceled','trialing')),
  dodo_subscription_id  text unique,
  current_period_end    timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- billing_events  (idempotency ledger for Dodo webhooks)
-- ----------------------------------------------------------------------------
create table public.billing_events (
  id              uuid primary key default gen_random_uuid(),
  subscription_id uuid references public.subscriptions (id) on delete restrict,
  event_type      text not null,
  idempotency_key text not null unique,   -- replay guard
  payload         jsonb not null default '{}'::jsonb,
  received_at     timestamptz not null default now()
);

create index idx_subscriptions_user        on public.subscriptions (user_id);
create index idx_billing_events_subscription on public.billing_events (subscription_id);

-- ============================================================================
-- RLS
-- Users may READ their own subscription. Writes come from the engine
-- (service role) handling webhooks; clients never write billing state.
-- billing_events is engine-only: no client policy, RLS on, so the
-- authenticated client sees nothing.
-- ============================================================================
alter table public.subscriptions enable row level security;
alter table public.billing_events enable row level security;

create policy subscriptions_owner_read on public.subscriptions
  for select using (auth.uid() = user_id);

-- (no client policy on billing_events: service-role only)
