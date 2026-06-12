# Clavis Database (Supabase / PostgreSQL)

Runnable SQL for the V0 schema. The ERD and design notes live in the Notion *"Database (ERD and
Design)"* page; **these files are the source of truth for what actually runs.**

## Apply order (do not reorder)

1. `clavis_v0_schema.sql` — core tables (`users`, `broker_credentials`, `strategies`,
   `strategy_versions`, `agent_logs`, `execution_history`), RLS policies, the Vault credential pattern,
   and the `anonymize_user()` GDPR routine.
2. `clavis_billing_schema.sql` — `subscriptions` + `billing_events` (the Dodo Payments idempotency
   ledger).
3. `clavis_live_schema.sql` — `strategies.deployment_status` (Deploy Hub) and
   `agent_logs.proposal_id` + the widened `user_decision` constraint (the live loop's
   pending -> decided capture pattern).

Billing **must** be applied second: `subscriptions.user_id` references `public.users(id)`, which the
core schema creates. The live-loop schema alters tables created in step 1, so it must be applied last.

## How to apply

- Supabase Dashboard → SQL Editor → paste each file and run, in order; **or**
- `psql "$SUPABASE_DB_URL" -f clavis_v0_schema.sql` then `-f clavis_billing_schema.sql`; **or**
- copy into Supabase migrations (`supabase/migrations/`), preserving the order.

## Ground rules baked into the schema

- **RLS on every table.** The browser (anon/authenticated key) sees only its own rows; the engine uses
  the service-role key, which bypasses RLS by design in Supabase.
- **Credentials are never stored raw.** `broker_credentials` holds metadata plus a Supabase Vault
  reference; decryption is service-role only.
- **`agent_logs` is the moat.** `ON DELETE RESTRICT` everywhere — never cascade-wiped. GDPR deletion is
  anonymize-and-detach via `anonymize_user()`, never a hard cascade.
- **Idempotent billing.** `billing_events.idempotency_key` is `UNIQUE`, so a replayed Dodo webhook is a
  no-op rather than a double state change.

Requires the `pgcrypto` extension (created by the core script) and the Supabase-provided `vault` schema.
