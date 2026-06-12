"""Deploy Hub persistence — strategies.deployment_status, RLS-scoped.

Every read/write carries the caller's Supabase JWT, so RLS scopes everything to
the owner (same pattern as engine/strategy_engine.py / engine/backtest_store.py).
The engine never uses the service role here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app import config


def _headers(token: str) -> dict[str, str]:
    return {
        "apikey": config.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",  # the USER's token -> RLS applies
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _url(path: str) -> str:
    return f"{config.SUPABASE_REST_URL}/{path}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _with_client(client: Optional[httpx.AsyncClient]):
    if client is not None:
        return client, False
    return httpx.AsyncClient(timeout=15.0), True


async def get_strategy(
    strategy_id: str, token: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[dict[str, Any]]:
    """Load a strategy the caller owns. RLS hides others' rows -> returns None."""
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url(f"strategies?id=eq.{strategy_id}&select=id,strategy_spec,deployment_status"),
            headers=_headers(token),
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None
    finally:
        if owns:
            await c.aclose()


async def count_deployed(
    token: str, *, exclude_strategy_id: str, client: Optional[httpx.AsyncClient] = None
) -> int:
    """How many of the caller's OTHER strategies are currently deployed."""
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url("strategies"),
            headers=_headers(token),
            params={
                "deployment_status": "eq.deployed",
                "id": f"neq.{exclude_strategy_id}",
                "select": "id",
            },
        )
        resp.raise_for_status()
        return len(resp.json())
    finally:
        if owns:
            await c.aclose()


async def set_deployment_status(
    strategy_id: str, deployment_status: str, token: str, client: Optional[httpx.AsyncClient] = None
) -> dict[str, Any]:
    """Flip deployment_status (the Deploy Hub's deploy / kill-switch action)."""
    c, owns = await _with_client(client)
    try:
        resp = await c.patch(
            _url(f"strategies?id=eq.{strategy_id}"),
            headers=_headers(token),
            json={"deployment_status": deployment_status, "updated_at": _now_iso()},
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else {}
    finally:
        if owns:
            await c.aclose()
