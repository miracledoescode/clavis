"""Clavis FastAPI engine — application composition root.

The path is always Frontend -> FastAPI -> Bridge. The ``bridge`` package exposes
no router and is never mounted here; it is internal infrastructure only.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app import config
from app.api import configure_cors, deploy_router, router, telegram_router
from app.api.routers.deploy import get_live_runner
from app.api.routers.telegram import get_agent_loop_registry
from app.engine.live_runner import LiveRunner
from app.integrations.telegram import set_webhook


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Starts the slice-4 live loop (if configured) and registers the
    Telegram webhook on boot. "The live process is disposable" — this IS the
    live process; `runner.start()` rebuilds everything from the broker,
    Postgres, and Redis (boot reconciliation)."""
    runner: LiveRunner | None = None
    if config.live_runner_configured():
        runner = LiveRunner()
        await runner.start()
        app.dependency_overrides[get_agent_loop_registry] = lambda: runner.registry
        app.dependency_overrides[get_live_runner] = lambda: runner

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_WEBHOOK_URL:
        await set_webhook(
            config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_WEBHOOK_URL, config.TELEGRAM_WEBHOOK_SECRET
        )

    yield

    if runner is not None:
        await runner.stop()
        app.dependency_overrides.pop(get_agent_loop_registry, None)
        app.dependency_overrides.pop(get_live_runner, None)


app = FastAPI(title="Clavis Engine", version="0.0.0", lifespan=lifespan)

# CORS lives in the API layer only (app/api/cors.py).
configure_cors(app)

# Public API routes. engine/, bridge/, and integrations/ are not routers.
app.include_router(router)

# Deploy Hub (deploy / kill-switch / status), under /v1/strategies.
app.include_router(deploy_router)

# Telegram webhook (Co-Pilot Approve/Reject). Telegram-authenticated, not under /v1.
app.include_router(telegram_router)
