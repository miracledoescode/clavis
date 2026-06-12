"""Live ConditionEvaluator: ticks -> bars -> Setup entry checklist.

Implements the `ConditionEvaluator` protocol from `agent_loop.py` against a
streaming tick feed. Reuses the same pure pandas evaluation helpers
(`engine/conditions.py`) as the backtester so live and backtest agree on what
"not modelled in V0" means.

`BarAggregator` rolls ticks into OHLC bars at the setup's entry timeframe.
`LiveConditionEvaluator.evaluate` only looks at the LAST bar of the resulting
frame (closed bars + the in-progress bar), so a setup can fire intrabar on the
forming bar — matching how a trader watching a chart would react.
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import pandas as pd

from app.contract.schemas import Setup
from app.engine.agent_loop import Tick
from app.engine.backtest_data import OHLCV_COLUMNS, timeframe_freq
from app.engine.conditions import _apply_filters, _eval_group

# --------------------------------------------------------------------------- #
# Bar aggregation                                                              #
# --------------------------------------------------------------------------- #


class BarAggregator:
    """Rolls a tick stream into OHLC bars at a fixed timeframe.

    Keeps up to `maxlen` CLOSED bars plus one in-progress bar. `to_frame()`
    returns both, with the in-progress bar as the last row, so indicators can
    react to the forming bar without waiting for it to close.
    """

    def __init__(self, timeframe: str, maxlen: int = 300) -> None:
        self._freq = timeframe_freq(timeframe)
        self._bars: deque[dict] = deque(maxlen=maxlen)
        self._current: Optional[dict] = None
        self._current_bucket: Optional[pd.Timestamp] = None

    def _bucket(self, ts) -> pd.Timestamp:
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        try:
            return t.floor(self._freq)
        except ValueError:
            # anchored offsets (e.g. "1W", "1MS") don't support floor(); fall
            # back to the start of day, which is coarser but never crashes.
            return t.normalize()

    def update(self, tick: Tick) -> None:
        bucket = self._bucket(tick.timestamp)
        price = tick.mid()
        if self._current is None or bucket != self._current_bucket:
            if self._current is not None:
                self._bars.append({**self._current, "_ts": self._current_bucket})
            self._current = {"open": price, "high": price, "low": price, "close": price, "volume": 0.0}
            self._current_bucket = bucket
        else:
            self._current["high"] = max(self._current["high"], price)
            self._current["low"] = min(self._current["low"], price)
            self._current["close"] = price

    @property
    def closed_bar_count(self) -> int:
        return len(self._bars)

    def to_frame(self) -> pd.DataFrame:
        rows = list(self._bars)
        if self._current is not None:
            rows = rows + [{**self._current, "_ts": self._current_bucket}]
        if not rows:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        index = pd.DatetimeIndex([r["_ts"] for r in rows])
        data = [{k: v for k, v in r.items() if k != "_ts"} for r in rows]
        return pd.DataFrame(data, index=index)[OHLCV_COLUMNS]


# --------------------------------------------------------------------------- #
# ConditionEvaluator                                                           #
# --------------------------------------------------------------------------- #


class LiveConditionEvaluator:
    """Evaluates a Setup's entry checklist against the live bar series.

    One instance per (symbol, entry timeframe) — i.e. one per AgentLoop, since
    a strategy has a single instrument and entry timeframe. Ticks for other
    symbols are ignored.
    """

    def __init__(self, symbol: str, entry_timeframe: str, min_bars: int = 250) -> None:
        self.symbol = symbol
        self.entry_timeframe = entry_timeframe
        self.min_bars = min_bars
        self._aggregator = BarAggregator(entry_timeframe)

    def evaluate(self, tick: Tick, setup: Setup) -> bool:
        if tick.symbol != self.symbol:
            return False

        self._aggregator.update(tick)
        if self._aggregator.closed_bar_count < self.min_bars:
            return False  # warmup: not enough history for indicators yet

        df = self._aggregator.to_frame()
        warnings: list[str] = []
        entries = _eval_group(setup.entry, df, warnings)
        entries = _apply_filters(entries, setup.filters, df, warnings)
        if entries.empty:
            return False
        return bool(entries.iloc[-1])
