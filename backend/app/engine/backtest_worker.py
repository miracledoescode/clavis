"""Backtest worker — VectorBT.

Baseline simulation of a validated StrategySpec over a slice of local OHLCV:
entries from each setup's checklist, SL/TP applied, per-setup per-trade-risk
sizing, session/time filters, and a configurable spread+slippage cost. The
simulation itself runs through `vbt.Portfolio.from_signals`; indicators are
computed in pandas for determinism. Output is deterministic for a fixed spec +
data slice.

An invalid spec NEVER runs — `run_backtest` validates against schemas.py first.
Every report carries the legally-required disclaimer (CLAUDE.md copy guardrail).

OUT OF SCOPE here: order execution, the agent loop, the behaviour-adjusted and
approval-delay modes (V1). This is the baseline report only.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import vectorbt as vbt
from pydantic import ValidationError

from app.contract.schemas import (
    ConditionGroup,
    Filters,
    Setup,
    StrategySpec,
)
from app.engine.backtest_data import pip_size, timeframe_freq

DISCLAIMER = (
    "Backtested results are hypothetical and based on historical data. Past "
    "performance does not guarantee future results. This is not financial advice "
    "and is not a promise or projection of returns. Trading carries risk, "
    "including the loss of capital."
)


class InvalidSpecError(ValueError):
    """Raised when the spec fails contract validation — the backtest never runs."""


@dataclass(frozen=True)
class BacktestConfig:
    init_cash: float = 100_000.0
    spread_pips: float = 0.6
    slippage_pips: float = 0.2
    fees_fraction: float = 0.00002
    max_leverage: float = 30.0
    equity_points: int = 240


# --------------------------------------------------------------------------- #
# Indicators (pandas; deterministic)                                          #
# --------------------------------------------------------------------------- #
def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def _sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period).mean()


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1.0 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _indicator_series(indicator: str, params: dict[str, Any], df: pd.DataFrame):
    name = indicator.lower()
    period = int(params.get("period", params.get("window", 14)) or 14)
    close = df["close"]
    if name == "ema":
        return _ema(close, period)
    if name in ("sma", "ma"):
        return _sma(close, period)
    if name == "rsi":
        return _rsi(close, period)
    if name == "atr":
        return _atr(df, period)
    if name == "macd":
        fast = int(params.get("fast", 12))
        slow = int(params.get("slow", 26))
        return _ema(close, fast) - _ema(close, slow)
    return None  # unsupported indicator


_REF_RE = re.compile(r"(ema|sma|rsi)\((\d+)\)", re.IGNORECASE)


def _reference_series(ref: str, df: pd.DataFrame):
    r = ref.strip().lower()
    mapping = {
        "price.close": df["close"], "close": df["close"],
        "price.open": df["open"], "open": df["open"],
        "price.high": df["high"], "high": df["high"],
        "price.low": df["low"], "low": df["low"],
    }
    if r in mapping:
        return mapping[r]
    m = _REF_RE.match(r)
    if m:
        return _indicator_series(m.group(1), {"period": int(m.group(2))}, df)
    return None


def _compare(a: pd.Series, comparator: str, b) -> pd.Series:
    if comparator == "gt":
        return a > b
    if comparator == "gte":
        return a >= b
    if comparator == "lt":
        return a < b
    if comparator == "lte":
        return a <= b
    if comparator == "eq":
        return a == b
    bs = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
    if comparator == "crosses_above":
        return (a > bs) & (a.shift(1) <= bs.shift(1))
    if comparator == "crosses_below":
        return (a < bs) & (a.shift(1) >= bs.shift(1))
    return pd.Series(False, index=a.index)


def _eval_condition(cond: Any, df: pd.DataFrame, warnings: list[str]) -> pd.Series:
    false = pd.Series(False, index=df.index)
    kind = cond.kind
    if kind == "indicator":
        series = _indicator_series(cond.indicator, cond.params, df)
        if series is None:
            warnings.append(f"unsupported indicator '{cond.indicator}' — treated as never-true")
            return false
        if cond.value is not None:
            rhs: Any = float(cond.value)
        elif cond.reference is not None:
            rhs = _reference_series(cond.reference, df)
            if rhs is None:
                warnings.append(f"unsupported reference '{cond.reference}' — treated as never-true")
                return false
        else:
            warnings.append("indicator condition has neither value nor reference — never-true")
            return false
        return _compare(series, cond.comparator, rhs).fillna(False)
    if kind == "candlestick":
        o, c = df["open"], df["close"]
        po, pc = o.shift(1), c.shift(1)
        if cond.pattern == "bullish_engulfing":
            return ((pc < po) & (c > o) & (c >= po) & (o <= pc)).fillna(False)
        if cond.pattern == "bearish_engulfing":
            return ((pc > po) & (c < o) & (c <= po) & (o >= pc)).fillna(False)
        warnings.append(f"candlestick pattern '{cond.pattern}' not modelled in V0 — never-true")
        return false
    warnings.append(f"condition kind '{kind}' not modelled in V0 — never-true")
    return false


def _eval_group(group: ConditionGroup, df: pd.DataFrame, warnings: list[str]) -> pd.Series:
    results = []
    for child in group.children:
        if isinstance(child, ConditionGroup):
            results.append(_eval_group(child, df, warnings))
        else:
            results.append(_eval_condition(child, df, warnings))
    combined = results[0]
    for r in results[1:]:
        combined = (combined & r) if group.operator == "all" else (combined | r)
    return combined.fillna(False)


# --------------------------------------------------------------------------- #
# Filters (session / time; news needs a calendar we do not fabricate)          #
# --------------------------------------------------------------------------- #
_SESSION_UTC = {  # approximate session windows in UTC hours [start, end)
    "sydney": (21, 6), "tokyo": (0, 9), "london": (7, 16), "new_york": (12, 21),
}


def _apply_filters(entries: pd.Series, filters: Filters | None, df: pd.DataFrame, warnings: list[str]) -> pd.Series:
    if filters is None:
        return entries
    idx = df.index
    if filters.time is not None and filters.time.enabled:
        tf = filters.time
        mask = pd.Series(True, index=idx)
        if tf.allowed_days:
            # contract: 0=Sun..6=Sat; pandas dayofweek: 0=Mon..6=Sun
            contract_dow = (idx.dayofweek + 1) % 7
            mask &= pd.Series(np.isin(contract_dow, tf.allowed_days), index=idx)
        start, end = tf.allowed_hours_utc.start, tf.allowed_hours_utc.end
        hours = idx.hour
        in_window = (hours >= start) & (hours < end) if start <= end else (hours >= start) | (hours < end)
        mask &= pd.Series(in_window, index=idx)
        entries = entries & mask
    if filters.sessions is not None and filters.sessions.enabled and filters.sessions.allowed_sessions:
        hours = idx.hour
        ok = pd.Series(False, index=idx)
        for s in filters.sessions.allowed_sessions:
            a, b = _SESSION_UTC[s]
            ok |= pd.Series((hours >= a) & (hours < b) if a <= b else (hours >= a) | (hours < b), index=idx)
        entries = entries & ok
    if filters.news is not None and filters.news.enabled:
        warnings.append("news filter present but no news calendar is loaded — not applied in V0")
    return entries


# --------------------------------------------------------------------------- #
# Per-setup stop/target fractions + risk sizing                                #
# --------------------------------------------------------------------------- #
def _stop_fractions(setup: Setup, df: pd.DataFrame, symbol: str, warnings: list[str]):
    close = df["close"]
    sl = setup.exit.stop_loss
    pip = pip_size(symbol)
    if sl.model == "fixed_pips":
        sl_dist = pd.Series(sl.value * pip, index=df.index)
    elif sl.model == "atr":
        sl_dist = sl.value * _atr(df, int(sl.atr_period or 14))
    else:  # "structure" — no level data in V0; proxy with 1.5x ATR(14)
        warnings.append("structure stop modelled as 1.5x ATR(14) in V0")
        sl_dist = 1.5 * _atr(df, 14)
    sl_frac = (sl_dist / close).clip(lower=1e-9)

    legs = setup.exit.take_profit
    if not legs:
        tp_frac = sl_frac * 2.0
    else:
        tp = legs[0]  # V0 uses the first leg; partial closes are Titan (gated later)
        if tp.model == "rr":
            tp_frac = sl_frac * tp.value
        elif tp.model == "fixed_pips":
            tp_frac = pd.Series(tp.value * pip, index=df.index) / close
        else:  # atr
            tp_frac = (tp.value * _atr(df, 14)) / close
    return sl_frac, tp_frac.clip(lower=1e-9)


def _risk_fraction(setup: Setup, cfg: BacktestConfig) -> float:
    ptr = setup.per_trade_risk
    if ptr.model == "fixed_percent":
        return float(ptr.value) / 100.0
    if ptr.model == "fixed_amount":
        return float(ptr.value) / cfg.init_cash
    return float(ptr.value) / 100.0  # atr_based: treat value as a percent in V0


def _run_setup(setup: Setup, spec: StrategySpec, df: pd.DataFrame, cfg: BacktestConfig, warnings: list[str]):
    symbol = spec.instrument.symbol
    entries = _eval_group(setup.entry, df, warnings)
    entries = _apply_filters(entries, setup.filters, df, warnings)
    sl_frac, tp_frac = _stop_fractions(setup, df, symbol, warnings)

    valid = sl_frac.notna() & (sl_frac > 0)
    entries = (entries & valid).fillna(False)

    p = _risk_fraction(setup, cfg)
    size = (p / sl_frac).where(valid, 0.0).clip(upper=cfg.max_leverage).fillna(0.0)

    slip_frac = (cfg.spread_pips / 2 + cfg.slippage_pips) * pip_size(symbol) / float(df["close"].median())
    direction = "longonly" if setup.direction == "long" else "shortonly"

    pf = vbt.Portfolio.from_signals(
        close=df["close"],
        entries=entries,
        sl_stop=sl_frac,
        tp_stop=tp_frac,
        size=size,
        size_type="percent",
        direction=direction,
        fees=cfg.fees_fraction,
        slippage=float(slip_frac),
        init_cash=cfg.init_cash,
        freq=timeframe_freq(spec.timeframes.entry),
    )

    value = pf.value()
    records = pf.trades.records_readable
    trades = []
    for _, t in records.iterrows():
        entry_ts = t["Entry Timestamp"]
        f = float(sl_frac.loc[entry_ts]) if entry_ts in sl_frac.index else float("nan")
        ret = float(t["Return"])
        r_mult = ret / f if f and f > 0 and not math.isnan(f) else 0.0
        trades.append({"pnl": float(t["PnL"]), "return": ret, "r": r_mult})
    return value, trades


# --------------------------------------------------------------------------- #
# Public entry point                                                           #
# --------------------------------------------------------------------------- #
def run_backtest(spec: Any, df: pd.DataFrame, config: BacktestConfig | None = None) -> dict[str, Any]:
    """Validate the spec, simulate every setup, return the report card payload.

    Deterministic for a fixed (spec, df). Raises InvalidSpecError if the spec does
    not validate against the contract — an unvalidated spec never runs.
    """
    cfg = config or BacktestConfig()
    raw = spec if isinstance(spec, dict) else spec.model_dump()
    try:
        validated = StrategySpec.model_validate(raw)
    except ValidationError as exc:
        raise InvalidSpecError(str(exc)) from exc

    if df is None or len(df) == 0:
        raise ValueError("no OHLCV data provided for the backtest window")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)

    warnings: list[str] = []
    per_setup_values: list[pd.Series] = []
    all_trades: list[dict[str, float]] = []
    for setup in validated.setups:
        value, trades = _run_setup(setup, validated, df, cfg, warnings)
        per_setup_values.append(value)
        all_trades.extend(trades)

    init = cfg.init_cash
    combined = pd.Series(init, index=df.index, dtype=float)
    for v in per_setup_values:
        combined = combined.add(v.reindex(df.index).ffill().fillna(init) - init, fill_value=0.0)

    summary = _summarize(combined, all_trades, init)
    return {
        "report_version": "1.0",
        "summary": summary,
        "equity_curve": _equity_curve(combined, cfg.equity_points),
        "meta": {
            "symbol": validated.instrument.symbol,
            "timeframe": validated.timeframes.entry,
            "setups": len(validated.setups),
            "bars": int(len(df)),
            "from": df.index[0].isoformat(),
            "to": df.index[-1].isoformat(),
            "init_cash": init,
            "costs": {
                "spread_pips": cfg.spread_pips,
                "slippage_pips": cfg.slippage_pips,
                "fees_fraction": cfg.fees_fraction,
            },
            "warnings": sorted(set(warnings)),
        },
        "disclaimer": DISCLAIMER,
    }


def _summarize(equity: pd.Series, trades: list[dict[str, float]], init: float) -> dict[str, Any]:
    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    rs = np.array([t["r"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    running_max = equity.cummax()
    drawdown = (equity / running_max - 1.0)
    profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else (float("inf") if wins.sum() > 0 else 0.0)
    return {
        "net_return": float(equity.iloc[-1] / init - 1.0),
        "max_drawdown": float(abs(drawdown.min())) if len(drawdown) else 0.0,
        "win_rate": float((pnls > 0).mean()) if len(pnls) else 0.0,
        "profit_factor": None if math.isinf(profit_factor) else round(profit_factor, 4),
        "expectancy_r": float(np.mean(rs)) if len(rs) else 0.0,
        "trade_count": int(len(trades)),
    }


def _equity_curve(equity: pd.Series, points: int) -> list[dict[str, float]]:
    if len(equity) > points:
        step = max(1, len(equity) // points)
        equity = equity.iloc[::step]
    return [
        {"time": int(ts.timestamp()), "value": round(float(v), 2)}
        for ts, v in equity.items()
    ]
