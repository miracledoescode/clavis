"""Broker symbol normalizer.

Brokers such as Exness / Justmarkets append suffixes (e.g. "EURUSD.m" -> suffix
".m"). This maps Clavis canonical symbols to broker-specific symbols and back.
Internal to the bridge; no public route. Scaffold stub — not implemented.
"""
from __future__ import annotations


def normalize(symbol: str, broker_symbol_suffix: str | None = None) -> str:
    """Apply a broker suffix to a canonical symbol (e.g. ``EURUSD`` + ``.m``).

    Scaffold stub — not implemented.
    """
    raise NotImplementedError("symbol_normalizer.normalize is a scaffold stub")
