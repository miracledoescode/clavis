"""OHLCV data access for the backtest worker.

Local store ONLY — never a broker feed (CLAUDE.md). The Dukascopy ingest writes
`{SYMBOL}_{TF}.parquet` with UTC timestamps under BACKTEST_DATA_DIR; the worker
reads it directly. A deterministic synthetic generator backs tests and benchmarks
with no network.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# pandas offset alias per Clavis timeframe.
_TF_FREQ = {
    "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
    "H1": "1h", "H4": "4h", "D1": "1D", "W1": "1W", "MN1": "1MS",
}

# Pip size in price units. JPY pairs and metals differ from the FX-major default.
_PIP = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001, "NZDUSD": 0.0001,
    "USDCHF": 0.0001, "USDCAD": 0.0001, "USDJPY": 0.01, "XAUUSD": 0.01,
}


def timeframe_freq(tf: str) -> str:
    return _TF_FREQ.get(tf, "1h")


def pip_size(symbol: str) -> float:
    s = symbol.upper()
    if s in _PIP:
        return _PIP[s]
    if s.endswith("JPY"):
        return 0.01
    return 0.0001


def data_path(data_dir: str, symbol: str, timeframe: str) -> str:
    return os.path.join(data_dir, f"{symbol.upper()}_{timeframe}.parquet")


def load_ohlcv(
    symbol: str,
    timeframe: str,
    data_dir: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """Load a normalized, UTC-indexed OHLCV frame from the local store."""
    path = data_path(data_dir, symbol, timeframe)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No market data at {path}. Run the Dukascopy ingest (scripts/ingest_dukascopy.mjs) first."
        )
    df = _normalize(pd.read_parquet(path))
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]
    return df


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        for c in ("timestamp", "time", "date", "datetime"):
            if c in df.columns:
                df = df.set_index(c)
                break
    df.index = pd.to_datetime(df.index, utc=True)
    df.columns = [str(c).lower() for c in df.columns]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[OHLCV_COLUMNS].sort_index()


def synthetic_ohlcv(
    symbol: str = "EURUSD",
    timeframe: str = "H1",
    bars: int = 600,
    seed: int = 7,
    start: str = "2020-01-01",
) -> pd.DataFrame:
    """Deterministic OHLCV for tests + benchmarks (no network, fixed seed)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start=pd.Timestamp(start, tz="UTC"), periods=bars, freq=timeframe_freq(timeframe))
    s = symbol.upper()
    base = 1900.0 if s == "XAUUSD" else (150.0 if s.endswith("JPY") else 1.10)
    close = base * np.exp(np.cumsum(rng.normal(0, 0.0015, bars)))
    open_ = np.empty(bars)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    wick = np.abs(rng.normal(0, 0.001, bars)) * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    volume = rng.integers(100, 1000, bars).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )
