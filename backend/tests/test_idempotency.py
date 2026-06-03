"""Pure idempotency helpers: deterministic key + should_send (duplicate guard)."""
from dataclasses import dataclass

import pytest

from app.engine.idempotency import idempotency_key, should_send


def test_explicit_proposal_id_is_the_key():
    assert idempotency_key({"proposal_id": "p1"}) == "p1"
    assert idempotency_key({"id": "p2"}) == "p2"


def test_object_proposal_supported():
    @dataclass
    class Proposal:
        proposal_id: str

    assert idempotency_key(Proposal("p9")) == "p9"


def test_key_is_deterministic_without_explicit_id():
    prop = {
        "strategy_id": "s1",
        "symbol": "EURUSD",
        "direction": "long",
        "proposed_at": "2026-06-03T12:00:00Z",
        "entry_price": 1.1,
    }
    k1 = idempotency_key(prop)
    k2 = idempotency_key(dict(prop))
    assert k1 == k2
    assert isinstance(k1, str) and k1
    # A different proposal yields a different key.
    assert idempotency_key({**prop, "symbol": "GBPUSD"}) != k1


def test_empty_proposal_raises():
    with pytest.raises(ValueError):
        idempotency_key({})


def test_should_send_suppresses_used_key():
    prop = {"proposal_id": "p1"}
    assert should_send(prop, set()) is True
    assert should_send(prop, {"p1"}) is False  # already produced an order -> suppress


def test_should_send_allows_new_key():
    assert should_send({"proposal_id": "pX"}, {"p1", "p2"}) is True
