"""MT5 bridge client — INTERNAL INFRASTRUCTURE ONLY.

No public ingress and no router: the bridge is never mounted on the FastAPI app.
The only path to it is Frontend -> FastAPI -> Bridge (CLAUDE.md). broker.py and
price_feed.py are HTTP clients for the self-hosted mt5-bridge/ service (see its
README) — not MetaApi, a paid per-account SaaS this project does not use.
"""
