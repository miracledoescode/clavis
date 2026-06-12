"""BarAggregator + LiveConditionEvaluator (live ConditionEvaluator impl).

Feeds a deterministic tick sequence through the aggregator and evaluator and
checks: bar rollover boundaries, warmup gating (min_bars), and that an
RSI-based setup only fires once warmup is satisfied AND the condition is true
on the latest bar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.contract.schemas import (
    ConditionGroup,
    ExitSpec,
    IndicatorCondition,
    PerTradeRisk,
    Setup,
    StopLoss,
    TakeProfitLeg,
)
from app.engine.agent_loop import Tick
from app.engine.condition_evaluator import BarAggregator, LiveConditionEvaluator

_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _tick(minute: int, price: float, symbol: str = "EURUSD") -> Tick:
    ts = _T0 + timedelta(minutes=minute)
    return Tick(symbol=symbol, bid=price, ask=price, timestamp=ts)


def _rsi_setup(period: int = 3) -> Setup:
    return Setup(
        name="RSI dip",
        direction="long",
        entry=ConditionGroup(
            operator="all",
            children=[
                IndicatorCondition(
                    kind="indicator",
                    indicator="RSI",
                    params={"period": period},
                    comparator="lt",
                    value=30.0,
                )
            ],
        ),
        exit=ExitSpec(
            stop_loss=StopLoss(model="fixed_pips", value=50),
            take_profit=[TakeProfitLeg(model="rr", value=2.0, close_percent=100)],
        ),
        per_trade_risk=PerTradeRisk(model="fixed_percent", value=1.0),
    )


# --------------------------------------------------------------------------- #
# BarAggregator                                                                #
# --------------------------------------------------------------------------- #


def test_bar_rolls_over_on_bucket_boundary():
    agg = BarAggregator("M1")

    # three ticks within the same minute bucket
    agg.update(_tick(0, 1.1000))
    agg.update(_tick(0, 1.1010))
    agg.update(_tick(0, 1.0990))
    assert agg.closed_bar_count == 0

    # a tick in the next minute closes bar 0
    agg.update(_tick(1, 1.1005))
    assert agg.closed_bar_count == 1

    df = agg.to_frame()
    closed = df.iloc[0]
    assert closed["open"] == 1.1000
    assert closed["high"] == 1.1010
    assert closed["low"] == 1.0990
    assert closed["close"] == 1.0990

    # in-progress bar is the last row
    current = df.iloc[-1]
    assert current["open"] == current["close"] == 1.1005
    assert len(df) == 2


# --------------------------------------------------------------------------- #
# LiveConditionEvaluator                                                       #
# --------------------------------------------------------------------------- #


def test_warmup_blocks_evaluation_before_min_bars():
    evaluator = LiveConditionEvaluator("EURUSD", "M1", min_bars=5)
    setup = _rsi_setup()

    # 5 ticks -> 4 closed bars, still below min_bars=5
    for i, price in enumerate([1.1000, 1.0990, 1.0980, 1.0970, 1.0960]):
        result = evaluator.evaluate(_tick(i, price), setup)
        assert result is False


def test_evaluate_ignores_other_symbols():
    evaluator = LiveConditionEvaluator("EURUSD", "M1", min_bars=5)
    setup = _rsi_setup()
    assert evaluator.evaluate(_tick(0, 1.1000, symbol="GBPUSD"), setup) is False


def test_rsi_setup_fires_once_warmed_up_and_condition_true():
    evaluator = LiveConditionEvaluator("EURUSD", "M1", min_bars=5)
    setup = _rsi_setup()

    # Monotonically declining closes -> RSI(3) trends to 0, well under 30.
    prices = [1.1000, 1.0990, 1.0980, 1.0970, 1.0960, 1.0950]
    results = [evaluator.evaluate(_tick(i, p), setup) for i, p in enumerate(prices)]

    # Below min_bars (first 5 ticks -> <5 closed bars): never fires.
    assert results[:5] == [False, False, False, False, False]
    # 6th tick -> 5 closed bars (warmup satisfied) + RSI(3) < 30 on the latest bar.
    assert results[5] is True
