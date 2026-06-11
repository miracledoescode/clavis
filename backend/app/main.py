"""Clavis FastAPI engine — application composition root.

The path is always Frontend -> FastAPI -> Bridge. The ``bridge`` package exposes
no router and is never mounted here; it is internal infrastructure only.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api import configure_cors, router, telegram_router

app = FastAPI(title="Clavis Engine", version="0.0.0")

# CORS lives in the API layer only (app/api/cors.py).
configure_cors(app)

# Public API routes. engine/, bridge/, and integrations/ are not routers.
app.include_router(router)

# Telegram webhook (Co-Pilot Approve/Reject). Telegram-authenticated, not under /v1.
app.include_router(telegram_router)
