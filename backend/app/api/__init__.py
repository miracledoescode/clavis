"""API layer: routers and CORS.

CORS is configured HERE only (see ``cors.py``) — the MT5 bridge has no public
ingress. ``main.py`` imports ``router`` and ``configure_cors`` from this package.
"""
from app.api.cors import configure_cors
from app.api.routes import router

__all__ = ["configure_cors", "router"]
