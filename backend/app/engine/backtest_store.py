"""Backtest persistence + strategy load — all under the caller's RLS context.

Every read/write carries the user's JWT, so RLS scopes everything to the owner:
a user can only load their OWN strategy to backtest, and only see their OWN
backtests. The engine never uses the service role here. (httpx -> PostgREST.)
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
) -> Optional[dict]:
    """Load a strategy the caller owns. RLS hides others' rows -> returns None."""
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url(f"strategies?id=eq.{strategy_id}&select=id,name,version,strategy_spec"),
            headers=_headers(token),
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None
    finally:
        if owns:
            await c.aclose()


async def create_backtest(
    *,
    user_id: str,
    strategy_id: str,
    strategy_version: Optional[int],
    params: dict[str, Any],
    token: str,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    c, owns = await _with_client(client)
    try:
        resp = await c.post(
            _url("backtests"),
            headers=_headers(token),
            json={
                "user_id": user_id,
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "params": params,
                "status": "queued",
            },
        )
        resp.raise_for_status()
        return resp.json()[0]
    finally:
        if owns:
            await c.aclose()


async def update_backtest(
    backtest_id: str,
    token: str,
    *,
    status: Optional[str] = None,
    report: Optional[dict] = None,
    error: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    body: dict[str, Any] = {}
    if status is not None:
        body["status"] = status
    if report is not None:
        body["report"] = report
    if error is not None:
        body["error"] = error
    if status in ("done", "error"):
        body["completed_at"] = _now_iso()

    c, owns = await _with_client(client)
    try:
        resp = await c.patch(
            _url(f"backtests?id=eq.{backtest_id}"), headers=_headers(token), json=body
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else {}
    finally:
        if owns:
            await c.aclose()


async def get_backtest(
    backtest_id: str, token: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[dict]:
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url(f"backtests?id=eq.{backtest_id}&select=*"), headers=_headers(token)
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None
    finally:
        if owns:
            await c.aclose()
