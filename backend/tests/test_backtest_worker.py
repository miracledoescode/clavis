"""Backtest worker tests.

(a) output is deterministic for a fixed spec + data slice
(b) an invalid / unvalidated spec is rejected before running
(d) the report payload carries the required disclaimer
+   a valid spec produces a populated report card
"""
import pytest

from app.engine.backtest_data import synthetic_ohlcv
from app.engine.backtest_worker import InvalidSpecError, run_backtest


def _spec(comparator: str = "lt", value: float = 40.0) -> dict:
    return {
        "schema_version": "1.0",
        "id": "rsi-bt",
        "name": "RSI backtest",
        "instrument": {"symbol": "EURUSD", "asset_class": "forex"},
        "timeframes": {"entry": "H1"},
        "setups": [
            {
                "name": "rsi long",
                "direction": "long",
                "entry": {
                    "operator": "all",
                    "children": [
                        {
                            "kind": "indicator",
                            "indicator": "rsi",
                            "params": {"period": 14},
                            "comparator": comparator,
                            "value": value,
                        }
                    ],
                },
                "exit": {
                    "stop_loss": {"model": "atr", "value": 1.5, "atr_period": 14},
                    "take_profit": [{"model": "rr", "value": 2.0, "close_percent": 100}],
                },
                "per_trade_risk": {"model": "fixed_percent", "value": 1.0},
            }
        ],
        "risk": {"guards": {"disallow_martingale": True, "disallow_averaging_down": True, "disallow_grid": True}},
        "execution": {"mode": "semi_auto"},
        "version": 1,
        "metadata": {
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "author_user_id": "",
        },
    }


def _df():
    return synthetic_ohlcv("EURUSD", "H1", bars=500, seed=7)


def test_invalid_spec_is_rejected_before_running():  # (b)
    with pytest.raises(InvalidSpecError):
        run_backtest({"schema_version": "1.0", "name": "broken"}, _df())


def test_report_carries_disclaimer():  # (d)
    report = run_backtest(_spec(), _df())
    assert "disclaimer" in report
    assert "Past performance does not guarantee future results" in report["disclaimer"]


def test_output_is_deterministic():  # (a)
    df = _df()
    spec = _spec()
    r1 = run_backtest(spec, df)
    r2 = run_backtest(spec, df)
    assert r1["summary"] == r2["summary"]
    assert r1["equity_curve"] == r2["equity_curve"]


def test_report_is_populated():
    report = run_backtest(_spec(), _df())
    s = report["summary"]
    assert s["trade_count"] >= 1
    for key in ("net_return", "max_drawdown", "win_rate", "expectancy_r", "trade_count"):
        assert key in s
    assert len(report["equity_curve"]) > 0
    assert report["meta"]["symbol"] == "EURUSD"
    assert report["meta"]["bars"] == 500
