"""API layer: routers and CORS.

CORS is configured HERE only (see ``cors.py``) — the MT5 bridge has no public
ingress. ``main.py`` imports ``router``, ``telegram_router``, and
``configure_cors`` from this package.
"""
from app.api.cors import configure_cors
from app.api.routers.deploy import router as deploy_router
from app.api.routers.telegram import router as telegram_router
from app.api.routes import router

__all__ = ["configure_cors", "deploy_router", "router", "telegram_router"]
