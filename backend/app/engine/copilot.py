"""Agent Co-Pilot: RLHF log writes.

Implements DecisionLogger (from agent_loop) against Supabase agent_logs — the
moat table. Writes every decision (approve / reject / invalidated / executed)
to agent_logs. ON DELETE RESTRICT; never cascade-wiped (CLAUDE.md).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app import config
from app.engine.agent_loop import ActiveProposal


def _service_headers() -> dict[str, str]:
    return {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{config.SUPABASE_REST_URL}/{path}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseDecisionLogger:
    """Writes proposals and their decisions to agent_logs (the RLHF seam)."""

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def _get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def log_proposal(self, proposal: ActiveProposal) -> None:
        c = await self._get()
        await c.post(
            _url("agent_logs"),
            headers=_service_headers(),
            json=self._row(proposal, decision="pending"),
        )

    async def log_decision(
        self,
        proposal: ActiveProposal,
        decision: str,
        reject_reason: Optional[str] = None,
    ) -> None:
        c = await self._get()
        await c.patch(
            _url(f"agent_logs?proposal_id=eq.{proposal.proposal_id}"),
            headers={**_service_headers(), "Prefer": "return=minimal"},
            json={
                "decision": decision,
                "reject_reason_chip": reject_reason,
                "logged_at": _now_iso(),
            },
        )

    def _row(self, p: ActiveProposal, decision: str) -> dict[str, Any]:
        return {
            "proposal_id": p.proposal_id,
            "strategy_id": p.strategy_id,
            "symbol": p.symbol,
            "direction": p.direction,
            "entry_price": p.entry_price,
            "stop_loss_price": p.stop_loss_price,
            "take_profit_prices": p.take_profit_prices,
            "confidence_score": p.confidence_score,
            "rationale": p.rationale,
            "proposed_at": p.proposed_at.isoformat(),
            "expires_at": p.expires_at.isoformat(),
            "decision": decision,
            "logged_at": _now_iso(),
        }

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
