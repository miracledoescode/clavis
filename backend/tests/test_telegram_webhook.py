"""Telegram webhook router: approve/reject callback_query -> AgentLoop.

Fakes AgentLoopRegistry/AgentLoop/StateStore/TelegramNotifier so the routing +
secret-token verification is exercised without a real Telegram bot, broker, or
Redis.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routers.telegram import get_agent_loop_registry
from app.main import app


class FakeStateStore:
    def __init__(self, pending: dict[str, dict] | None = None, used_keys: set[str] | None = None):
        self.pending = pending or {}
        self.used_keys = used_keys or set()

    async def get_pending_proposal(self, proposal_id):
        return self.pending.get(proposal_id)

    async def used_idempotency_keys(self):
        return set(self.used_keys)


class FakeTelegram:
    def __init__(self):
        self.answered: list[tuple[str, str | None]] = []

    async def answer_callback_query(self, callback_query_id, text=None):
        self.answered.append((callback_query_id, text))


class FakeLoop:
    def __init__(self, pending: dict[str, dict] | None = None):
        self.state_store = FakeStateStore(pending)
        self.telegram = FakeTelegram()
        self.approved: list[tuple[str, set]] = []
        self.rejected: list[str] = []

    async def on_approval(self, proposal_id, used_keys):
        self.approved.append((proposal_id, used_keys))

    async def on_rejection(self, proposal_id, reason=None):
        self.rejected.append(proposal_id)


class FakeRegistry:
    def __init__(self, loop: FakeLoop | None):
        self._loop = loop

    async def get_loop_for_proposal(self, proposal_id):
        if self._loop is not None and proposal_id in self._loop.state_store.pending:
            return self._loop
        return None


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_secret(monkeypatch):
    monkeypatch.setattr("app.api.routers.telegram.config.TELEGRAM_WEBHOOK_SECRET", "")


def _callback_update(action: str, proposal_id: str, callback_id: str = "cb1") -> dict:
    return {
        "update_id": 1,
        "callback_query": {
            "id": callback_id,
            "data": f"{action}:{proposal_id}",
        },
    }


def test_approve_callback_invokes_on_approval():
    loop = FakeLoop(pending={"p1": {"symbol": "EURUSD"}})
    loop.state_store.used_keys = {"old-key"}
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    client = TestClient(app)
    resp = client.post("/telegram/webhook", json=_callback_update("approve", "p1"))

    assert resp.status_code == 200
    assert loop.approved == [("p1", {"old-key"})]
    assert loop.rejected == []
    assert loop.telegram.answered == [("cb1", None)]


def test_reject_callback_invokes_on_rejection():
    loop = FakeLoop(pending={"p1": {"symbol": "EURUSD"}})
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    client = TestClient(app)
    resp = client.post("/telegram/webhook", json=_callback_update("reject", "p1"))

    assert resp.status_code == 200
    assert loop.rejected == ["p1"]
    assert loop.approved == []
    assert loop.telegram.answered == [("cb1", None)]


def test_unknown_proposal_is_a_noop():
    loop = FakeLoop(pending={})
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    client = TestClient(app)
    resp = client.post("/telegram/webhook", json=_callback_update("approve", "p404"))

    assert resp.status_code == 200
    assert loop.approved == []
    assert loop.telegram.answered == []


def test_non_callback_update_is_ignored():
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(None)

    client = TestClient(app)
    resp = client.post("/telegram/webhook", json={"update_id": 1, "message": {"text": "/start"}})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_unrecognized_callback_data_is_ignored():
    loop = FakeLoop(pending={"p1": {"symbol": "EURUSD"}})
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    client = TestClient(app)
    resp = client.post("/telegram/webhook", json=_callback_update("snooze", "p1"))

    assert resp.status_code == 200
    assert loop.approved == []
    assert loop.rejected == []


# --------------------------------------------------------------------------- #
# Webhook secret verification                                                  #
# --------------------------------------------------------------------------- #
def test_missing_secret_header_rejected_when_configured(monkeypatch):
    monkeypatch.setattr("app.api.routers.telegram.config.TELEGRAM_WEBHOOK_SECRET", "shh")
    loop = FakeLoop(pending={"p1": {"symbol": "EURUSD"}})
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    client = TestClient(app)
    resp = client.post("/telegram/webhook", json=_callback_update("approve", "p1"))

    assert resp.status_code == 401
    assert loop.approved == []


def test_correct_secret_header_accepted(monkeypatch):
    monkeypatch.setattr("app.api.routers.telegram.config.TELEGRAM_WEBHOOK_SECRET", "shh")
    loop = FakeLoop(pending={"p1": {"symbol": "EURUSD"}})
    app.dependency_overrides[get_agent_loop_registry] = lambda: FakeRegistry(loop)

    client = TestClient(app)
    resp = client.post(
        "/telegram/webhook",
        json=_callback_update("approve", "p1"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "shh"},
    )

    assert resp.status_code == 200
    assert loop.approved == [("p1", set())]


def test_registry_not_configured_returns_503():
    client = TestClient(app)
    resp = client.post("/telegram/webhook", json=_callback_update("approve", "p1"))
    assert resp.status_code == 503
