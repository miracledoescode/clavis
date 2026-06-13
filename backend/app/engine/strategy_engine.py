"""Strategy engine: persistence + versioning.

Every write goes through the caller's authenticated context — we forward the
user's Supabase JWT to PostgREST so RLS scopes the row to its owner. The engine
NEVER uses the service-role key here; ownership is enforced by the database, not
by trust in the API layer.

  create:  insert strategies (version 1) + snapshot into strategy_versions
  update:  bump version, patch strategies, write a new strategy_versions snapshot

Validation against the contract (schemas.py) happens at the API boundary before
any function here runs — unvalidated specs never reach this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app import config


def _headers(token: str) -> dict[str, str]:
    return {
        "apikey": config.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",  # the USER's token → RLS applies
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


async def create_strategy(
    *, user_id: str, name: str, spec: dict[str, Any], token: str,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Insert a new strategy at version 1 and snapshot it."""
    c, owns = await _with_client(client)
    try:
        resp = await c.post(
            _url("strategies"),
            headers=_headers(token),
            json={"user_id": user_id, "name": name, "strategy_spec": spec, "version": 1},
        )
        resp.raise_for_status()
        row = resp.json()[0]
        snap = await c.post(
            _url("strategy_versions"),
            headers=_headers(token),
            json={"strategy_id": row["id"], "version": 1, "spec_snapshot": spec},
        )
        snap.raise_for_status()
        return row
    finally:
        if owns:
            await c.aclose()


async def update_strategy(
    *, strategy_id: str, name: Optional[str], spec: dict[str, Any], token: str,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Bump the version, patch the strategy, and snapshot the new version."""
    c, owns = await _with_client(client)
    try:
        current = await c.get(
            _url(f"strategies?id=eq.{strategy_id}&select=version"),
            headers=_headers(token),
        )
        current.raise_for_status()
        rows = current.json()
        if not rows:
            # RLS hides others' rows, so "not found" also covers "not yours".
            raise StrategyNotFound(strategy_id)
        new_version = int(rows[0]["version"]) + 1

        patch_body: dict[str, Any] = {
            "strategy_spec": spec,
            "version": new_version,
            "updated_at": _now_iso(),
        }
        if name is not None:
            patch_body["name"] = name

        patched = await c.patch(
            _url(f"strategies?id=eq.{strategy_id}"),
            headers=_headers(token),
            json=patch_body,
        )
        patched.raise_for_status()
        row = patched.json()[0]

        snap = await c.post(
            _url("strategy_versions"),
            headers=_headers(token),
            json={"strategy_id": strategy_id, "version": new_version, "spec_snapshot": spec},
        )
        snap.raise_for_status()
        return row
    finally:
        if owns:
            await c.aclose()


async def list_strategies(
    *, token: str, client: Optional[httpx.AsyncClient] = None
) -> list[dict[str, Any]]:
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url(
                "strategies?select=id,name,version,status,deployment_status,updated_at"
                "&order=updated_at.desc"
            ),
            headers=_headers(token),
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            await c.aclose()


class StrategyNotFound(Exception):
    """Raised when a strategy id is not visible to the caller (missing or not owned)."""

    def __init__(self, strategy_id: str) -> None:
        super().__init__(f"Strategy {strategy_id} not found")
        self.strategy_id = strategy_id
