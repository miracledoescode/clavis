"""Runtime settings, env-driven.

Scaffold note: plain ``os.getenv`` with no extra dependency (``pydantic-settings``
can come later). This module is the single source of truth for the default Claude
model string and the CORS allow-list, so they never drift across the codebase.
"""
from __future__ import annotations

import os

# --- AI -------------------------------------------------------------------- #
# Default Claude model. CLAUDE.md mandates claude-sonnet-4-6 (never a 2024-era
# string). Integrations import this rather than hard-coding their own default.
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# --- CORS (configured in the API layer ONLY; see app/api/cors.py) ---------- #
CORS_ALLOW_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

# --- Supabase -------------------------------------------------------------- #
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
# Used to verify the Supabase JWT (RS256 / JWKS) once real verification lands.
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")
