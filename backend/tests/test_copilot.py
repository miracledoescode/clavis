"""SupabaseDecisionLogger (test (d)).

Uses httpx.MockTransport to stand in for Supabase PostgREST, so the
agent_logs write shapes (pending row on log_proposal, decision PATCH on
log_decision) are verified without network. Row shape must match
clavis_v0_schema.sql + clavis_live_schema.sql.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.engine.agent_loop import ActiveProposal
from app.engine.copilot import SupabaseDecisionLogger

_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    from app.engine import copilot

    monkeypatch.setattr(copilot.config, "SUPABASE_REST_URL", "http://rest.test")
    monkeypatch.setattr(copilot.config, "SUPABASE_SERVICE_ROLE_KEY", "service-key")


def _make_proposal() -> ActiveProposal:
    return ActiveProposal(
        proposal_id="p1",
        strategy_id="s1",
        symbol="EURUSD",
        direction="long",
        entry_price=1.1000,
        stop_loss_price=1.0950,
        take_profit_prices=[1.1100],
        confidence_score=0.7,
        rationale="test",
        proposed_at=_T0,
        expires_at=_T0 + timedelta(minutes=5),
        sl_distance=0.005,
        user_id="u1",
    )


def test_log_proposal_writes_pending_row():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/agent_logs")
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json=[{}])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            logger = SupabaseDecisionLogger(client=client)
            await logger.log_proposal(_make_proposal())

    asyncio.run(run())

    body = captured["body"]
    assert body["strategy_id"] == "s1"
    assert body["user_id"] == "u1"
    assert body["proposal_id"] == "p1"
    assert body["user_decision"] == "pending"
    assert body["confidence_score"] == 0.7
    assert "logged_at" in body

    proposal = body["proposal"]
    assert proposal["strategy_id"] == "s1"
    assert proposal["symbol"] == "EURUSD"
    assert proposal["direction"] == "long"
    assert proposal["entry_price"] == 1.1000
    assert proposal["stop_loss_price"] == 1.0950
    assert proposal["take_profit_prices"] == [1.1100]
    assert proposal["rationale"] == "test"
    assert proposal["proposed_at"] == _T0.isoformat()
    assert proposal["expires_at"] == (_T0 + timedelta(minutes=5)).isoformat()


def test_log_decision_patches_by_proposal_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path.endswith("/agent_logs")
        captured["query"] = str(request.url.params)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{}])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            logger = SupabaseDecisionLogger(client=client)
            await logger.log_decision(_make_proposal(), "reject", reject_reason="bad_fill")

    asyncio.run(run())

    assert captured["query"] == "proposal_id=eq.p1"
    body = captured["body"]
    assert body["user_decision"] == "reject"
    assert body["reject_reason_chip"] == "bad_fill"
    assert "logged_at" in body
