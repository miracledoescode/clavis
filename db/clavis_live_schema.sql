-- ============================================================================
-- Clavis live-loop schema  ::  Supabase (PostgreSQL)
-- Additive changes needed to wire the slice-4 live loop end to end:
--   - strategies.deployment_status: what the live runner loads at boot and
--     what the Deploy Hub (deploy / kill switch) flips.
--   - agent_logs.proposal_id + a widened user_decision constraint: the V0
--     capture loop writes a 'pending' row when a proposal is sent
--     (log_proposal) and later PATCHes it to the final decision
--     (log_decision), keyed by proposal_id.
-- Apply AFTER clavis_v0_schema.sql and clavis_billing_schema.sql.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- strategies.deployment_status
-- ----------------------------------------------------------------------------
alter table public.strategies
  add column deployment_status text not null default 'stopped'
    check (deployment_status in ('stopped', 'deployed'));

-- The live runner's boot query (`deployment_status = 'deployed'`) is the only
-- thing that scans this column at any volume.
create index idx_strategies_deployment_status on public.strategies (deployment_status)
  where deployment_status = 'deployed';

-- ----------------------------------------------------------------------------
-- agent_logs.proposal_id (+ 'pending' decision state)
-- ----------------------------------------------------------------------------
alter table public.agent_logs
  add column proposal_id text;

create index idx_agent_logs_proposal_id on public.agent_logs (proposal_id);

-- log_proposal writes 'pending' at proposal time; log_decision later PATCHes
-- the same row (matched by proposal_id) to the final decision.
alter table public.agent_logs
  drop constraint agent_logs_user_decision_check;

alter table public.agent_logs
  add constraint agent_logs_user_decision_check
    check (user_decision in ('pending', 'approve', 'reject', 'invalidated', 'executed'));
