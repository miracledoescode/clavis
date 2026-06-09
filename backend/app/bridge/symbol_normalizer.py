"""Broker symbol normalizer.

Brokers such as Exness / Justmarkets append suffixes to symbol names
(e.g. "EURUSD.m"). This module maps between Clavis canonical symbols and
broker-specific symbols in both directions. Internal to the bridge — no public
route.
"""
from __future__ import annotations


def normalize(symbol: str, broker_symbol_suffix: str | None = None) -> str:
    """Return the broker-specific symbol by appending the suffix.

    ``normalize("EURUSD", ".m")`` → ``"EURUSD.m"``
    ``normalize("EURUSD", None)`` → ``"EURUSD"``

    A leading dot is added if the suffix does not already start with one.
    """
    if not broker_symbol_suffix:
        return symbol
    suffix = (
        broker_symbol_suffix
        if broker_symbol_suffix.startswith(".")
        else f".{broker_symbol_suffix}"
    )
    return f"{symbol}{suffix}"


def denormalize(broker_symbol: str, broker_symbol_suffix: str | None = None) -> str:
    """Strip the broker suffix to recover the canonical symbol.

    ``denormalize("EURUSD.m", ".m")`` → ``"EURUSD"``
    ``denormalize("EURUSD", None)``    → ``"EURUSD"``

    No-ops when the symbol does not end with the expected suffix.
    """
    if not broker_symbol_suffix:
        return broker_symbol
    suffix = (
        broker_symbol_suffix
        if broker_symbol_suffix.startswith(".")
        else f".{broker_symbol_suffix}"
    )
    if broker_symbol.endswith(suffix):
        return broker_symbol[: -len(suffix)]
    return broker_symbol
