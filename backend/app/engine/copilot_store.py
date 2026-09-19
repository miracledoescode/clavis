"""Co-Pilot persistence — reads of agent_logs, RLS-scoped.

Every read carries the caller's Supabase JWT, so RLS (`agent_logs_owner`)
scopes everything to the owner — same pattern as `engine/deploy_store.py`.
The engine never uses the service role here; writes to agent_logs stay in
`engine/copilot.py::SupabaseDecisionLogger` (service role, called from the
live loop only — never directly from a web request).
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from app import config

_SELECT = "proposal_id,strategy_id,proposal,user_decision,reject_reason_chip,confidence_score,logged_at"


def _headers(token: str) -> dict[str, str]:
    return {
        "apikey": config.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",  # the USER's token -> RLS applies
    }


def _url(path: str) -> str:
    return f"{config.SUPABASE_REST_URL}/{path}"


async def _with_client(client: Optional[httpx.AsyncClient]):
    if client is not None:
        return client, False
    return httpx.AsyncClient(timeout=15.0), True


async def list_pending_proposals(
    token: str, client: Optional[httpx.AsyncClient] = None
) -> list[dict[str, Any]]:
    """The caller's pending proposals, newest first."""
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url("agent_logs"),
            headers=_headers(token),
            params={
                "user_decision": "eq.pending",
                "select": _SELECT,
                "order": "logged_at.desc",
            },
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            await c.aclose()


async def get_pending_proposal(
    proposal_id: str, token: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[dict[str, Any]]:
    """A single pending proposal the caller owns. RLS hides others' rows -> None."""
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url("agent_logs"),
            headers=_headers(token),
            params={
                "proposal_id": f"eq.{proposal_id}",
                "user_decision": "eq.pending",
                "select": _SELECT,
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None
    finally:
        if owns:
            await c.aclose()


async def list_decisions(
    token: str,
    limit: int = 50,
    offset: int = 0,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """The caller's decided proposals (approve/reject/invalidated/executed)."""
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url("agent_logs"),
            headers=_headers(token),
            params={
                "user_decision": "neq.pending",
                "select": _SELECT,
                "order": "logged_at.desc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            await c.aclose()
