"""Rule Builder parse route tests.

- a parsed spec validates against schemas.py and the inference hints are stripped
- an ambiguous prompt triggers clarification, not a spec
- a martingale prompt is blocked (deterministically, before any model call)
- (d) an inferred direction is returned for confirmation, not auto-finalized
- an explicit direction does not require confirmation
- an incomplete spec reports what is missing

(Contract-shape tests (a)/(b)/(c) live in test_contract_smoke.py.)
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes import get_claude_call
from app.contract.schemas import StrategySpec
from app.main import app


def _setup(direction, comparator, inferred=True, rationale="implied by the checklist"):
    """A Claude-style setup, including the parse-time inference hints."""
    return {
        "name": f"{direction} reversion",
        "direction": direction,
        "direction_inferred": inferred,
        "direction_rationale": rationale,
        "entry": {
            "operator": "all",
            "children": [
                {
                    "kind": "indicator",
                    "indicator": "rsi",
                    "params": {"period": 14},
                    "comparator": comparator,
                    "value": 30,
                }
            ],
        },
        "exit": {
            "stop_loss": {"model": "atr", "value": 1.5, "atr_period": 14},
            "take_profit": [{"model": "rr", "value": 2.5, "close_percent": 100}],
        },
        "per_trade_risk": {"model": "fixed_percent", "value": 1.0},
    }


def _claude_spec(setups):
    return {
        "schema_version": "1.0",
        "id": "rsi-reversion",
        "name": "RSI reversion",
        "instrument": {"symbol": "EURUSD", "asset_class": "forex"},
        "timeframes": {"entry": "H1"},
        "setups": setups,
        "risk": {
            "guards": {
                "disallow_martingale": True,
                "disallow_averaging_down": True,
                "disallow_grid": True,
            }
        },
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
    spec = _claude_spec([_setup("long", "crosses_below"), _setup("short", "crosses_above")])
    _set_claude_reply(json.dumps({"type": "spec", "spec": spec}))
    r = client.post(
        "/strategies/parse",
        json={"text": "RSI reversion both ways on EURUSD H1, 1% risk, 1.5 ATR stop, 2.5R"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "spec"
    # The returned spec validates and the parse-time inference hints were stripped.
    validated = StrategySpec.model_validate(body["spec"])
    assert len(validated.setups) == 2
    assert "direction_inferred" not in body["spec"]["setups"][0]
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
    assert body["type"] == "clarification"
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
    assert body["type"] == "block"
    assert "martingale" in body["patterns"]
    assert calls["n"] == 0  # blocked before Claude is ever called


def test_inferred_direction_returned_for_confirmation(client):  # (d)
    spec = _claude_spec(
        [_setup("long", "crosses_below", inferred=True, rationale="RSI crossing below 30 implies a long")]
    )
    _set_claude_reply(json.dumps({"type": "spec", "spec": spec}))
    r = client.post(
        "/strategies/parse",
        json={"text": "enter when RSI crosses below 30 on EURUSD H1, 1% risk, 1.5 ATR stop, 2.5R"},
    )
    body = r.json()
    assert body["type"] == "spec"
    # The side is PROPOSED for confirmation, never auto-finalized.
    assert body["requires_direction_confirmation"] is True
    assert body["setups"][0]["inferred"] is True
    assert body["setups"][0]["direction"] == "long"
    assert body["setups"][0]["rationale"]


def test_explicit_direction_does_not_require_confirmation(client):
    spec = _claude_spec(
        [_setup("short", "crosses_above", inferred=False, rationale="trader explicitly said short")]
    )
    _set_claude_reply(json.dumps({"type": "spec", "spec": spec}))
    r = client.post(
        "/strategies/parse",
        json={"text": "short EURUSD H1 when RSI crosses above 70, 1% risk, 1.5 ATR stop, 2.5R"},
    )
    body = r.json()
    assert body["requires_direction_confirmation"] is False
    assert body["setups"][0]["inferred"] is False


def test_incomplete_spec_reports_missing(client):
    _set_claude_reply(json.dumps({"type": "spec", "spec": {"schema_version": "1.0", "name": "x"}}))
    r = client.post("/strategies/parse", json={"text": "long eurusd"})
    body = r.json()
    assert body["type"] == "incomplete"
    assert body["missing"]
