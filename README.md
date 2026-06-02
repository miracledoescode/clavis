# Clavis

AI-native, no-code workspace where retail traders **design → build → backtest → deploy** autonomous
trading **Agents** on MetaTrader 5 (via MetaApi). An Agent applies only the logic the trader authored —
it never originates a recommendation the user did not encode.

> Backtest and simulation results are historical and do not guarantee future performance.

## Monorepo layout

```
clavis/
  frontend/   Next.js 14 (App Router, TS, Tailwind v3, shadcn/ui) — host: Vercel
  backend/    FastAPI engine (Pydantic v2, Docker) — host: Railway
  db/         Supabase Postgres schema (core + billing): RLS, Vault, GDPR
  CLAUDE.md   Engineering constitution — read this first
```

The **Strategy JSON** is the single source of truth, mirrored in two languages:
`frontend/src/contract/types.ts` ↔ `backend/app/contract/schemas.py`. They are one artifact in two
languages — change one and change the other in the **same commit** (`schema_version "1.0"`).

## Prerequisites

- Node.js ≥ 18 and npm (this repo was built with Node 22 / npm 10)
- Python 3.11
- Docker (optional — for the backend image)
- A Supabase project, plus keys for MetaApi, Claude (Anthropic), Dodo Payments, Telegram, and Upstash

## Frontend

```bash
cd frontend
npm install
cp .env.example .env.local      # fill in the NEXT_PUBLIC_* values
npm run dev                     # http://localhost:3000
npm run typecheck               # tsc --noEmit
npm run build
```

## Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt    # runtime deps + pytest
cp .env.example .env                   # fill in secrets — never commit .env
uvicorn app.main:app --reload          # http://localhost:8000  (try GET /health)
pytest -q                              # contract smoke test
```

Docker:

```bash
cd backend
docker build -t clavis-engine .
docker run --env-file .env -p 8000:8000 clavis-engine
```

## Database (Supabase)

Apply in order — billing references `public.users` from core:

1. `db/clavis_v0_schema.sql`
2. `db/clavis_billing_schema.sql`

RLS is on for every table: the browser uses the Supabase **anon key** and sees only its own rows; the
engine uses the **service-role key**. Credentials are stored as Vault references, never raw. See
`db/README.md`.

## Build sequence (from CLAUDE.md — do not reorder)

1. **Contract** — `types.ts` + `schemas.py` as a matched pair (`schema_version "1.0"`).
2. **Database** — apply core then billing (RLS, Vault, GDPR from day one).
3. **Engine shell** — FastAPI app, Supabase JWT auth on every request, CORS at the API layer only, the
   internal MT5 bridge with the symbol normalizer.
4. **Rule Builder + Strategy Engine** — canvas → StrategySpec → validate → persist + version.
5. **Backtest Lab → Paper Arena → Co-Pilot + Deploy Hub** — the V0 capture loop that writes every
   decision to `agent_logs`.

V0 ends at the log write. There is no training in V0 — the RLHF trainer, drift detector, and DNA
clustering are V1. Crypto (CCXT) is V2.

## Status

**Scaffold only.** Module folders under `frontend/src/modules/` are placeholders, and the backend
`engine/`, `bridge/`, and `integrations/` packages are stubs. Read `CLAUDE.md` before extending.
