"""HTTP routes for the public API surface.

Scaffold: a public health check plus one protected route that proves the Supabase
JWT dependency is wired. Real module routers (strategies, backtests, co-pilot,
deploy) are added later under this package — never the bridge, which stays
internal.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user

router = APIRouter()


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/api/me", tags=["auth"])
async def me(principal: dict = Depends(get_current_user)) -> dict[str, str]:
    """Echo the authenticated principal. Scaffold placeholder proving auth wiring."""
    return {"user_id": principal["user_id"]}
