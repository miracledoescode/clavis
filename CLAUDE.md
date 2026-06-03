# CLAUDE.md — Clavis Engineering Operating Manual

You are the founding principal engineer on Clavis. Read this file fully before
writing code, and keep it open. It is the constitution. When a request
conflicts with it, this file wins; flag the conflict rather than silently
breaking a rule.

-----

## What Clavis is

An AI-native, no-code workspace where retail traders design, build, backtest,
and deploy autonomous trading **Agents** — on a trading **execution platform**
(MetaTrader 5, starting with MT5 mobile FX), never directly with a broker.

Verb chain: **design -> build -> backtest -> deploy.**

The full loop from “I have a strategy” to “my strategy is running” must be
achievable in under 30 minutes on first use.

-----

## Non-negotiable rules (the constitution)

1. **Trader as principal, Clavis as tool.** Agents apply only the user’s
   authored logic. They never originate a recommendation the user did not
   encode. This keeps us out of investment-advice / CTA territory. Do not add
   features that generate or suggest strategies the user did not author.
1. **SL/TP at the broker, always.** Every live order carries its stop loss and
   take profit on the order itself, at the broker — not only inside the Clavis
   loop. An outage must never leave an unmanaged position. The engine enforces
   this regardless of any flag.
1. **The MT5 bridge is internal infrastructure.** It has no public ingress.
   Path is always Frontend -> FastAPI -> Bridge. CORS is configured at the
   FastAPI API layer ONLY.
1. **RLS on every table.** The browser uses the anon/authenticated key and sees
   only its own rows. The engine uses the service role key. No exceptions.
1. **Credentials are never stored raw.** Metadata + a Supabase Vault reference,
   service-role decryption only, bound to our servers via MetaApi IP
   whitelisting. KMS envelope encryption is the first hardening after MVP.
1. **The word is “Agent”, never “bot”.** Agents make judgments and explain
   them. This applies to code identifiers, comments, UI copy, everything.
1. **agent_logs is the moat.** It is the RLHF capture table. ON DELETE RESTRICT.
   Never cascade-wipe it. GDPR deletion is anonymize-and-detach, never a hard
   cascade (see `anonymize_user()` in `clavis_v0_schema.sql`).
1. **Dangerous patterns are guarded off by default.** Martingale, averaging
   down, grids are denied in `RiskGuards`. Enabling them is a deliberate,
   logged action that trips the classifier for human review.

-----

## The contract (single source of truth)

The Strategy JSON is the single source of truth across every module. The Rule
Builder canvas compiles to it; the engine executes only it; the backtester,
paper arena, and deploy hub all read it.

- `frontend/src/contract/types.ts`  — TypeScript definitions
- `backend/app/contract/schemas.py` — Pydantic v2 definitions

**These two files are one artifact in two languages.** They use identical
snake_case keys so the serialized JSON is byte-identical in either direction.
If you change one, change the other in the SAME commit. Keep BOTH pinned in
your context window whenever you touch anything that reads or writes a
strategy. `schema_version` is `"1.0"`; bump it deliberately, never by accident.

**Canonical 1.0 shape is SETUPS.** A trader authors a checklist of what must be
true, and the side follows — they do not author "buy X when". So a `StrategySpec`
is one or more `setups` (minimum 1). Each `Setup` is a single-direction checklist:
`{ name, direction (long|short, never "both"), entry: ConditionGroup, confluence?,
filters?, exit, per_trade_risk }`. The strategy holds `instrument`, `timeframes`,
`setups`, `execution`, `metadata`, `version`, and a strategy-level `risk` of only
`{ session?, account?, guards }` (caps + the default-deny guards, applied across
all setups). There is NO top-level `direction`/`entry`/`exit` and no top-level
per-trade risk. No production strategies were ever persisted, so this setups shape
**is** `schema_version "1.0"` — no migration. Direction guardrail: the parser may
PROPOSE a setup's side but never finalizes an inferred direction; the user confirms
every setup's direction before a spec is considered authored.

-----

## Verified stack (checked against live docs — do not substitute silently)

**Frontend / deploy**

- Next.js 14+, TypeScript, Tailwind, shadcn/ui
- React Flow via `@xyflow/react` (NOT the legacy `reactflow` package)
- TradingView Lightweight Charts (Apache 2.0; enable `attributionLogo`)
- Host: Vercel (edge)

**Backend / engine**

- FastAPI (Python), Docker, host: Railway
- VectorBT for backtests (Apache 2.0 + Commons Clause; fine as a component)
- MetaApi (cloud MT4/MT5, no Windows VPS) for execution; MetaStats for the
  trader profile. SL/TP set on the order at the broker.
- CCXT for crypto exchange integration — **post-MVP**, not V0.

**Data**

- Supabase: Postgres + Auth + Realtime. Realtime pushes live P&L.
- Supabase Vault for credentials (managed secrets, key outside the DB).
- Upstash Redis: cache, queues, rate counters.

**AI**

- Claude API for the strategy NLP parsing. Use the current Sonnet model
  string `claude-sonnet-4-6`. Do NOT use any 2024-era string from old docs.

**Payments**

- Dodo Payments (Merchant of Record). Handles global tax, pays out to Nigeria
  and India, recurring subscriptions, Standard Webhooks spec. Paddle is the
  fallback. (Stripe is out: it does not onboard Nigeria-based businesses.)

**Target infra cost:** under $40/month at MVP, trending toward zero with
startup credits.

-----

## Repo structure

```
clavis/
  frontend/                  # Next.js 14+ app (Vercel)
    src/
      contract/types.ts      # <- Strategy JSON contract (TS half)
      app/                   # routes
      modules/
        rule-builder/        # React Flow canvas -> StrategySpec
        backtest-lab/        # Lightweight Charts + report card
        paper-arena/         # Supabase Realtime dashboard
        deploy-hub/          # deploy, kill switch, status
        co-pilot/            # approve/reject UI, RLHF surface
      lib/                   # supabase client, api client
  backend/                   # FastAPI engine (Railway, Docker)
    app/
      contract/schemas.py    # <- Strategy JSON contract (Python half)
      api/                   # routers; CORS configured HERE only
      engine/
        agent_loop.py        # match -> propose -> validate -> execute
        strategy_engine.py   # versioning, Strategy JSON eval
        copilot.py           # approve/reject, RLHF log writes
        backtest_worker.py   # VectorBT
        tier_enforcer.py     # tier gating + billing checks
      bridge/                # MT5/MetaApi bridge — INTERNAL ONLY, no public route
        symbol_normalizer.py # handles broker suffixes e.g. EURUSD.m
      integrations/          # claude, telegram, dodo
  db/
    clavis_v0_schema.sql     # core tables, RLS, Vault pattern, GDPR fn
    clavis_billing_schema.sql# subscriptions + billing_events (Dodo)
  CLAUDE.md                  # this file
```

-----

## Build sequence (do not reorder)

1. **Contract first.** Land `types.ts` and `schemas.py` as a matched pair with
   `schema_version "1.0"`. Everything imports from these.
1. **Database.** Apply `clavis_v0_schema.sql` then `clavis_billing_schema.sql`.
   RLS, Vault reference pattern, and the GDPR routine exist from day one, not
   as a later retrofit.
1. **Engine shell.** FastAPI app, auth (verify Supabase RS256 JWT on every
   request), CORS at the API layer only, the internal bridge with the symbol
   normalizer.
1. **Rule Builder + Strategy Engine.** First, because they exercise the
   contract end to end (canvas -> StrategySpec -> validate -> persist + version).
1. **Backtest Lab**, then **Paper Arena**, then **Co-Pilot + Deploy Hub** (the
   V0 capture loop that writes every decision to `agent_logs`).

V0 ends at the log write. There is NO training in V0. The RLHF trainer, drift
detector, and DNA clustering are V1, built only once enough decision data
exists. Do not build them early.

-----

## The V0 capture loop (what the engine actually does)

1. Live price feed reaches the FastAPI agent loop.
1. Match conditions against the Strategy JSON.
1. On a match, send a proposal to Telegram with Approve/Reject. Start a hard
   5-minute validity window.
1. Circuit breaker: if price slips past 50% of the stop distance while pending,
   auto-invalidate.
1. On Approve, verify the window is STILL valid **before** sending, then place
   the order via MetaApi with SL and TP at the broker.
1. Write the decision (approve / reject-with-reason-chip / invalidated /
   executed) to `agent_logs`; execution outcome to `execution_history`.

-----

## State and Recovery (the live-engine safety contract)

SL and TP live at the broker on every order, so a process crash never leaves a
position unprotected. The real risks on restart are different: **lost
monitoring, state drift, and double execution.** This is the contract the live
loop (slice 4) is built against; the pure parts already exist and are tested.

**Three layers of truth.**
- The **broker** (via MetaApi) is AUTHORITATIVE for what positions and orders
  actually exist. When records disagree, the broker wins.
- **Postgres** is the durable record (strategies, versions, `agent_logs`,
  `execution_history`).
- **Upstash Redis** holds HOT state only: pending proposals + their validity
  windows, idempotency keys, and open-position flags. Hot state is a cache and a
  coordination layer, never the source of truth.

**Reconcile before acting — every boot.** Before the loop resumes, the engine
MUST run a reconciliation pass:
1. Fetch real broker state (open positions, working orders).
2. Load expected state (Postgres durable record + Redis hot state).
3. Diff them and act: **adopt** broker positions Clavis does not recognise
   (bring under management, NEVER open a duplicate); **close_out** expected
   positions the broker no longer shows (they hit SL/TP while we were down —
   record the outcome to `execution_history`); **invalidate** proposals whose
   validity window expired during downtime.
4. Only THEN resume the loop.
The pure diff is `engine/reconciliation.py::reconcile(...)` (no I/O, clock passed
in).

**Idempotency.** Every order send carries a client key — the `proposal_id` —
PERSISTED before the send (`engine/idempotency.py`; Redis marker via StateStore).
On restart, never resend a key that already produced a broker order;
`should_send(proposal, used_keys)` is the gate. This is what prevents double
execution.

**The live process is disposable.** ZERO authoritative state in process memory —
everything needed to recover lives in the broker, Postgres, and Redis, so any
instance can be killed and replaced mid-flight. Any V1 ML runs in a SEPARATE
worker, NEVER inside the execution loop.

Interfaces the live loop implements against (stubs until slice 4):
`bridge/broker.py::BrokerAdapter` (MetaApi; internal only — `place_order`
requires SL/TP) and `engine/hot_state.py::StateStore` (Upstash Redis; the Redis
key schema is documented there).

-----

## Execution mode fits timeframe

Co-Pilot (semi-auto, per-trade human approval) fits HIGHER-timeframe and swing
setups, where approval latency is small relative to stop distance. The approve/
reject loop is realistically 5 to 30+ seconds end to end.

On low-timeframe / tight-stop setups (scalping), that latency means the circuit
breaker (invalidate past 50% of the stop distance) fires before the human can
approve. Co-Pilot is therefore the WRONG mode for scalping — this is correct
behaviour, not a bug.

Scalping requires **Full Auto** (no human in the execution path). Full Auto is
the highest-liability mode and is **OUT OF V0**. It is a post-validation
capability with its own hardening bar: per-minute execution caps, a latency
budget, fat-finger guards, and a kill switch tested under load. Do not build
Full Auto in V0.

V0 supports Co-Pilot for higher-timeframe / swing / intraday only. Scalpers are
welcome as users; their fit is Full Auto, which comes later.

Rationale (record it): Co-Pilot's approve/reject IS the RLHF signal that feeds
V1. Full Auto logs outcomes but not preference data. Leaning V0 on Co-Pilot
maximizes the moat data.

**Co-Pilot suitability warning (Rule Builder requirement).** When a setup's entry
timeframe and stop distance imply approval latency would routinely trip the
circuit breaker, the Rule Builder MUST flag the strategy as unsuitable for
Co-Pilot and explain why — framed as "needs Full Auto, post-V0", never as a
defect. Computed purely from the setup's entry timeframe and stop distance, both
already in the StrategySpec. The pure check is
`engine/copilot_suitability.py::assess_copilot_suitability(...)`; its latency
assumption and circuit-breaker fraction are documented, configurable constants
(the fraction defaults to 0.5, matching `ExecutionSpec`). Only the pure check
exists now; the UI surface is built in slice 4.

-----

## DNA Engine data gate (V1)

The DNA Engine (ML archetype clustering) is V1 and must not ship without a
minimum data gate. Below the gate, do NOT surface archetypes at all. Build
nothing for it now — this records the constraint.

Distinguish clearly:
- **Trader Profile** = descriptive MetaStats. V0, valid at ANY sample size.
- **DNA Engine** = ML clustering into archetypes. V1, GATED.

Gate: a configurable minimum of closed trades (default **300**; a heuristic
floor, not a statistical law). Below it, show the descriptive profile plus a
"connect more history to unlock DNA" state — never a half-formed archetype.

Even above the gate, archetypes are presented as TENDENCIES with explicit
uncertainty, never as a guaranteed edge (legal posture: no promises — see the
Copy / legal guardrail).

-----

## The four hard problems (design-stage — do NOT claim “solved”)

1. NLP ambiguity -> clarification pass + completeness checker.
1. RLHF reward design -> two-layer preference learning vs drift, process-based
   eval. (V1.)
1. Agent backtesting -> three modes: baseline, behavior-adjusted sim,
   approval-delay distribution.
1. Dangerous vagueness -> martingale/averaging-down classifier flags before any
   block generation.

When you implement any of these, build the guardrail; do not mark it done until
it actually runs and is tested.

-----

## Copy / legal guardrail (applies to any user-facing string you write)

A non-custodial software posture does NOT protect against regulators if
marketing language promises easy returns (the SageMaster CSSF/FMA case). Never
write UI copy, error text, or docs that imply guaranteed or easy profit. Frame
Agents as executing the user’s own authored logic. Backtest results always
carry the in-UI disclaimer.

-----

## How to work here

- Keep `types.ts` and `schemas.py` in context together. Treat divergence
  between them as a build break.
- Prefer boring, battle-tested choices. This is an MVP: optimize for time to
  learning, not architectural elegance. Do not build the post-revenue ephemeral
  container execution architecture now — MetaApi at beta stage is correct until
  its economics force the change.
- Validate every inbound `StrategySpec` against `schemas.py` before it reaches
  the agent loop. Unvalidated strategies never run.
- Write tests around the contract, the validity-window check, the circuit
  breaker, and the RLS policies. Those are the load-bearing safety surfaces.
