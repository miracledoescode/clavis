"""Rule Builder parse route tests.

(a) a parsed spec validates against schemas.py
(b) an ambiguous prompt triggers clarification, not a spec
(c) a martingale prompt is blocked (deterministically, before any model call)
+   an incomplete spec reports what is missing
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes import get_claude_call
from app.contract.schemas import StrategySpec
from app.main import app

VALID_SPEC = {
    "schema_version": "1.0",
    "id": "ema-pullback",
    "name": "EMA 200 pullback",
    "instrument": {"symbol": "EURUSD", "asset_class": "forex"},
    "timeframes": {"entry": "H1"},
    "direction": "long",
    "entry": {
        "conditions": {
            "operator": "all",
            "children": [
                {
                    "kind": "indicator",
                    "indicator": "ema",
                    "params": {"period": 200},
                    "comparator": "gt",
                    "reference": "price.close",
                }
            ],
        }
    },
    "exit": {
        "stop_loss": {"model": "atr", "value": 1.5, "atr_period": 14},
        "take_profit": [{"model": "rr", "value": 2.0, "close_percent": 100}],
    },
    "risk": {"per_trade": {"model": "fixed_percent", "value": 1.0}},
    "execution": {"mode": "semi_auto"},
    "version": 1,
    "metadata": {
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "author_user_id": "",
    },
}


def _fake_user():
    return {"user_id": "00000000-0000-0000-0000-000000000000", "token": "t", "claims": {}}


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = _fake_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _set_claude_reply(reply: str) -> None:
    app.dependency_overrides[get_claude_call] = lambda: (lambda text: reply)


def test_parse_returns_validated_spec(client):
    _set_claude_reply(json.dumps({"type": "spec", "spec": VALID_SPEC}))
    r = client.post(
        "/strategies/parse",
        json={"text": "EMA200 pullback long on EURUSD H1, risk 1%, 1.5 ATR stop, 2R target"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "spec"
    # (a) the returned spec round-trips through the contract.
    StrategySpec.model_validate(body["spec"])
    assert body["spec"]["execution"]["broker_managed_sl_tp"] is True


def test_ambiguous_prompt_triggers_clarification(client):
    _set_claude_reply(
        json.dumps(
            {
                "type": "clarification",
                "questions": [
                    {"id": "timeframe", "question": "Which timeframe?", "why": "entry tf required"}
                ],
            }
        )
    )
    r = client.post("/strategies/parse", json={"text": "buy when it looks strong"})
    body = r.json()
    assert body["type"] == "clarification"  # (b) not a spec
    assert body["questions"]


def test_martingale_prompt_is_blocked(client):
    calls = {"n": 0}

    def fake(text):
        calls["n"] += 1
        return "{}"

    app.dependency_overrides[get_claude_call] = lambda: fake
    r = client.post(
        "/strategies/parse",
        json={"text": "Use a martingale: double my lot size after every loss until I recover"},
    )
    body = r.json()
    assert body["type"] == "block"  # (c) dangerous pattern blocked
    assert "martingale" in body["patterns"]
    assert calls["n"] == 0  # blocked before Claude is ever called


def test_incomplete_spec_reports_missing(client):
    _set_claude_reply(json.dumps({"type": "spec", "spec": {"schema_version": "1.0", "name": "x"}}))
    r = client.post("/strategies/parse", json={"text": "long eurusd"})
    body = r.json()
    assert body["type"] == "incomplete"
    assert body["missing"]
