"""Runtime settings, env-driven.

Single source of truth for the default Claude model, the CORS allow-list, and
the Supabase coordinates used for JWT verification and PostgREST writes.
"""
from __future__ import annotations

import os


def _split_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


# --- AI -------------------------------------------------------------------- #
# CLAUDE.md mandates claude-sonnet-4-6 (never a 2024-era string).
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# --- Supabase -------------------------------------------------------------- #
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").rstrip("/")
# Browser/anon publishable key; also sent as the PostgREST `apikey` header.
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

# JWT verification. Supabase issues asymmetric (RS256/ES256) access tokens when
# JWT signing keys are enabled; we verify them against the project JWKS. The
# legacy HS256 shared-secret path is supported as a fallback if SUPABASE_JWT_SECRET
# is set (the task targets RS256, which needs no secret — only the public JWKS).
SUPABASE_JWKS_URL: str = os.getenv(
    "SUPABASE_JWKS_URL",
    f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else "",
)
SUPABASE_JWT_ISSUER: str = os.getenv(
    "SUPABASE_JWT_ISSUER", f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else ""
)
SUPABASE_JWT_AUDIENCE: str = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")  # legacy HS256 only

# --- CORS (configured in the API layer ONLY; see app/api/cors.py) ---------- #
CORS_ALLOW_ORIGINS: list[str] = _split_origins(
    os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
)

# PostgREST base for engine-mediated writes under the user's JWT.
SUPABASE_REST_URL: str = f"{SUPABASE_URL}/rest/v1" if SUPABASE_URL else ""
