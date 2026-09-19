# Clavis MT5 Bridge

A thin HTTP wrapper around MetaQuotes' free, official `MetaTrader5` Python
package. This is the self-hosted, subscription-free alternative to MetaApi:
it runs where an actual MT5 terminal runs, and the main Clavis engine talks
to it over HTTP instead of importing the package directly (the package only
ships Windows wheels and only talks to a terminal on the *same machine*).

## Why this is a separate service

The main engine (`backend/`) is a Linux Docker container on Railway. It
cannot import `MetaTrader5` — there is no Linux build, and the package
requires local IPC with a running terminal. So this piece exists to run on
the one machine that *can* satisfy both: a Windows VPS with MT5 installed.

## Setup

1. Provision a small Windows VPS (any provider; a few dollars/month in
   compute is the only recurring cost — there is no per-account SaaS fee).
2. Install MetaTrader 5 and log into your (demo or live) account through the
   terminal UI once, so the terminal has cached the connection.
3. Install Python 3.11+ and this service:
   ```
   pip install -r requirements.txt
   ```
4. Set environment variables:
   - `MT5_LOGIN` — the account number
   - `MT5_PASSWORD` — the account's investor or trading password
   - `MT5_SERVER` — the broker's server name (as shown in the terminal)
   - `MT5_BRIDGE_SECRET` — a long random string; the engine sends this as a
     bearer token on every request
   - `MT5_TERMINAL_PATH` (optional) — path to `terminal64.exe` if it isn't on
     the default install path
   - `MT5_DEVIATION_POINTS` (optional, default `20`) — max price slippage
     tolerated on market orders, in points
5. Run it:
   ```
   uvicorn app:app --host 0.0.0.0 --port 8001
   ```

## Safety — no public ingress

CLAUDE.md's rule for the MT5 bridge ("internal infrastructure, no public
ingress") applies here just as much as it did to MetaApi. **Do not expose
this service's port to the public internet.** Put it behind a firewall and
reach it from the main engine only over a private network or VPN (e.g.
Tailscale, a VPC peering link, or an SSH tunnel). The bearer secret is
defense-in-depth, not a substitute for network isolation — this endpoint can
place real orders.

## Configuring the main engine

On the `backend/` side, set:
- `MT5_BRIDGE_URL` — this service's private URL, e.g. `http://100.x.y.z:8001`
- `MT5_BRIDGE_SECRET` — must match this service's `MT5_BRIDGE_SECRET`
- `MT5_SYMBOL_SUFFIX` (optional) — broker-specific suffix, e.g. `.m`
- `MT5_POLL_INTERVAL_SECONDS` (optional, default `1.0`) — how often the engine
  polls this service for price ticks (MT5 has no native push/streaming API,
  so polling is how the local path works, unlike MetaApi's streaming
  connection)

## Known limitations vs. MetaApi

- **No streaming ticks.** MT5's local API has no push mechanism; the engine
  polls `/tick` per symbol at `MT5_POLL_INTERVAL_SECONDS`. Faster polling
  costs a little more terminal load; slower polling means proposals react
  slightly later to price moves.
- **No broker-side idempotency key.** MetaApi accepted a `clientId` that let
  the broker itself reject an exact duplicate order. MT5's `comment` field is
  unreliable for this (brokers commonly truncate it well under its
  documented 31-character limit), so this bridge only tags a short
  diagnostic hash into `comment`. The real duplicate-order guard is Clavis's
  own pre-send idempotency check (`engine/idempotency.py`), which runs
  before this service is ever called.
- **Single account per running terminal.** Unlike MetaApi's per-account
  connection objects, one `MetaTrader5` Python process talks to exactly one
  logged-in terminal. Multi-account support would mean running one bridge
  instance (and one terminal) per account.
