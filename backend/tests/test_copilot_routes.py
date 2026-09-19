"""Co-Pilot web routes: list proposals/decisions, approve/reject.

`get_current_user` and `get_agent_loop_registry` are overridden via FastAPI
dependency_overrides (the registry override is the same function object
telegram.py depends on, so this exercises the shared-wiring contract too);
`copilot_store`'s PostgREST calls are monkeypatched directly, so no real
network/DB/Redis is needed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routers.telegram import get_agent_loop_registry
from app.engine import copilot_store
from app.main import app

PRINCIPAL = {"user_id": "user-1", "token": "user-jwt"}

PROPOSAL_ROW = {
    "proposal_id": "p1",
    "strategy_id": "strat-1",
    "proposal": {
        "strategy_id": "strat-1",
        "symbol": "EURUSD",
        "direction": "long",
        "entry_price": 1.1,
        "stop_loss_price": 1.095,
        "take_profit_prices": [1.11],
        "confidence_score": 0.7,
        "rationale": "Setup matched",
        "proposed_at": "2026-06-09T00:00:00Z",
        "expires_at": "2026-06-09T00:05:00Z",
    },
    "user_decision": "pending",
    "reject_reason_chip": None,
    "confidence_score": 0.7,
    "logged_at": "2026-06-09T00:00:00Z",
}


class FakeLoop:
    def __init__(self):
        self.state_store = AsyncMock()
        self.state_store.used_idempotency_keys = AsyncMock(return_value={"old-key"})
        self.on_approval = AsyncMock()
        self.on_rejection = AsyncMock()


class FakeRegistry:
    def __init__(self, loop):
        self._loop = loop

    async def get_loop_for_proposal(self, proposal_id):
        return self._loop


@pytest.fixture(autouse=True)
def _override_user():
    app.dependency_overrides[get_current_user] = lambda: PRINCIPAL
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_agent_loop_registry, None)


@pytest.fixture
def client():
    return TestClient(app)


# --------------------------------------------------------------------------- #
# reads                                                                        #
# --------------------------------------------------------------------------- #


def test_list_proposals(client, monkeypatch):
    monkeypatch.setattr(
        copilot_store, "list_pending_proposals", AsyncMock(return_value=[PROPOSAL_ROW])
    )
    resp = client.get("/v1/copilot/proposals")
    assert resp.status_code == 200
    assert resp.json() == [PROPOSAL_ROW]
    copilot_store.list_pending_proposals.assert_awaited_once_with("user-jwt")


def test_list_decisions(client, monkeypatch):
    monkeypatch.setattr(copilot_store, "list_decisions", AsyncMock(return_value=[]))
    resp = client.get("/v1/copilot/decisions?limit=10&offset=5")
    assert resp.status_code == 200
    assert resp.json() == []
    copilot_store.list_decisions.assert_awaited_once_with("user-jwt", limit=10, offset=5)


# --------------------------------------------------------------------------- #
# approve                                                                      #
# --------------------------------------------------------------------------- #


def test_approve_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        copilot_store, "get_pending_proposal", AsyncMock(return_value=PROPOSAL_ROW)
    )
    loop = FakeLoop()
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    resp = client.post("/v1/copilot/proposals/p1/approve")

    assert resp.status_code == 200
    assert resp.json() == {"proposal_id": "p1", "status": "approved"}
    loop.on_approval.assert_awaited_once_with("p1", {"old-key"})


def test_approve_not_owned_returns_404(client, monkeypatch):
    monkeypatch.setattr(copilot_store, "get_pending_proposal", AsyncMock(return_value=None))
    loop = FakeLoop()
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    resp = client.post("/v1/copilot/proposals/p1/approve")

    assert resp.status_code == 404
    loop.on_approval.assert_not_awaited()


def test_approve_no_active_loop_returns_409(client, monkeypatch):
    monkeypatch.setattr(
        copilot_store, "get_pending_proposal", AsyncMock(return_value=PROPOSAL_ROW)
    )
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(None)

    resp = client.post("/v1/copilot/proposals/p1/approve")

    assert resp.status_code == 409


def test_approve_registry_not_configured_returns_503(client, monkeypatch):
    monkeypatch.setattr(
        copilot_store, "get_pending_proposal", AsyncMock(return_value=PROPOSAL_ROW)
    )
    resp = client.post("/v1/copilot/proposals/p1/approve")
    assert resp.status_code == 503


# --------------------------------------------------------------------------- #
# reject                                                                       #
# --------------------------------------------------------------------------- #


def test_reject_with_reason_chip(client, monkeypatch):
    monkeypatch.setattr(
        copilot_store, "get_pending_proposal", AsyncMock(return_value=PROPOSAL_ROW)
    )
    loop = FakeLoop()
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    resp = client.post(
        "/v1/copilot/proposals/p1/reject", json={"reason_chip": "bad_timing"}
    )

    assert resp.status_code == 200
    assert resp.json() == {"proposal_id": "p1", "status": "rejected"}
    loop.on_rejection.assert_awaited_once_with("p1", "bad_timing")


def test_reject_without_body(client, monkeypatch):
    monkeypatch.setattr(
        copilot_store, "get_pending_proposal", AsyncMock(return_value=PROPOSAL_ROW)
    )
    loop = FakeLoop()
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    resp = client.post("/v1/copilot/proposals/p1/reject", json={})

    assert resp.status_code == 200
    loop.on_rejection.assert_awaited_once_with("p1", None)


def test_reject_not_owned_returns_404(client, monkeypatch):
    monkeypatch.setattr(copilot_store, "get_pending_proposal", AsyncMock(return_value=None))
    loop = FakeLoop()
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    resp = client.post("/v1/copilot/proposals/p1/reject", json={})

    assert resp.status_code == 404
    loop.on_rejection.assert_not_awaited()
