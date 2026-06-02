"""CORS configuration.

CLAUDE.md rule: the MT5 bridge has no public ingress, and CORS is configured at
the FastAPI API layer ONLY. Keeping every bit of CORS wiring in this one module
makes that rule structurally true and trivial to audit.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ALLOW_ORIGINS


def configure_cors(app: FastAPI) -> None:
    """Attach the single CORS middleware for the public API surface."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
