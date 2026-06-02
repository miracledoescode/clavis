"""Smoke test: a minimal StrategySpec validates against the Pydantic contract.

Also asserts the constitution's safety defaults survive validation: broker-managed
SL/TP, the hard 5-minute validity window, the 50% circuit breaker, and the
dangerous-pattern guards (martingale / averaging-down / grid) all default ON.
"""
from app.contract.schemas import StrategySpec

MINIMAL_SPEC = {
    "schema_version": "1.0",
    "id": "smoke-0001",
    "name": "Smoke Test Strategy",
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
        "author_user_id": "00000000-0000-0000-0000-000000000000",
    },
}


def test_minimal_strategyspec_validates() -> None:
    spec = StrategySpec.model_validate(MINIMAL_SPEC)
    assert spec.schema_version == "1.0"
    # Round-trips back to a plain dict without raising.
    assert spec.model_dump()["instrument"]["symbol"] == "EURUSD"


def test_safety_defaults_hold() -> None:
    spec = StrategySpec.model_validate(MINIMAL_SPEC)
    # SL/TP always at the broker — engine enforces regardless; defaulted True here.
    assert spec.execution.broker_managed_sl_tp is True
    # Hard 5-minute proposal validity window.
    assert spec.execution.validity_window_seconds == 300
    # Circuit breaker: invalidate past 50% of the stop distance.
    assert spec.execution.circuit_breaker.slip_invalidate_fraction == 0.5
    # Dangerous patterns are guarded OFF by default (deny).
    assert spec.risk.guards.disallow_martingale is True
    assert spec.risk.guards.disallow_averaging_down is True
    assert spec.risk.guards.disallow_grid is True
