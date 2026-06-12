"""Shared, pure condition-evaluation helpers.

Extracted from backtest_worker.py so the backtester and the live
ConditionEvaluator (engine/condition_evaluator.py) evaluate a Setup's entry
conditions identically. Conditions "not modelled in V0" (structure, bias,
price_level, most candlestick patterns) evaluate to False in both places, so
Co-Pilot suitability assessments and backtest expectations match live
behaviour.

All functions here are pandas-vectorized and I/O-free.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from app.contract.schemas import ConditionGroup, Filters

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
