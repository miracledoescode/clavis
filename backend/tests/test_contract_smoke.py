"""Smoke + shape tests for the StrategySpec contract (setups model).

Asserts the constitution's safety defaults survive validation (broker-managed
SL/TP, the hard 5-minute validity window, the 50% circuit breaker, and the
default-deny guards) and the setups shape behaves:
  (a) a multi-setup strategy validates
  (b) a setup with an empty checklist is rejected
  (c) a setup direction outside {long, short} is rejected
"""
import pytest
from pydantic import ValidationError

from app.contract.schemas import StrategySpec


def _setup(direction: str, comparator: str = "crosses_below") -> dict:
    return {
        "name": f"{direction} reversion",
        "direction": direction,
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


def _spec(setups: list[dict]) -> dict:
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
            "author_user_id": "00000000-0000-0000-0000-000000000000",
        },
    }


MINIMAL_SPEC = _spec([_setup("long")])


def test_minimal_strategyspec_validates() -> None:
    spec = StrategySpec.model_validate(MINIMAL_SPEC)
    assert spec.schema_version == "1.0"
    assert spec.model_dump()["instrument"]["symbol"] == "EURUSD"
    assert len(spec.setups) == 1


def test_safety_defaults_hold() -> None:
    spec = StrategySpec.model_validate(MINIMAL_SPEC)
    # SL/TP always at the broker — engine enforces regardless; defaulted True here.
    assert spec.execution.broker_managed_sl_tp is True
    # Hard 5-minute proposal validity window.
    assert spec.execution.validity_window_seconds == 300
    # Circuit breaker: invalidate past 50% of the stop distance.
    assert spec.execution.circuit_breaker.slip_invalidate_fraction == 0.5
    # Dangerous patterns are guarded OFF by default (deny), now strategy-level.
    assert spec.risk.guards.disallow_martingale is True
    assert spec.risk.guards.disallow_averaging_down is True
    assert spec.risk.guards.disallow_grid is True


def test_multi_setup_strategy_validates() -> None:  # (a)
    spec = StrategySpec.model_validate(
        _spec([_setup("long", "crosses_below"), _setup("short", "crosses_above")])
    )
    assert [s.direction for s in spec.setups] == ["long", "short"]
    # Per-trade risk lives on each setup now, not at strategy level.
    assert spec.setups[0].per_trade_risk.value == 1.0


def test_strategy_requires_at_least_one_setup() -> None:
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(_spec([]))


def test_setup_with_empty_checklist_is_rejected() -> None:  # (b)
    bad = _setup("long")
    bad["entry"]["children"] = []
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(_spec([bad]))


def test_setup_direction_outside_long_short_is_rejected() -> None:  # (c)
    bad = _setup("long")
    bad["direction"] = "both"
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(_spec([bad]))
