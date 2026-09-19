"""Fakes the `MetaTrader5` package (Windows-only, can't install here) so
app.py's request/response mapping and error handling can be exercised on any
OS. Same technique the main backend used for metaapi_cloud_sdk fakes.
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

import pytest

# app.py lives one directory up (mt5-bridge/), not on sys.path by default
# when pytest is invoked from within tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["MT5_LOGIN"] = "12345"
os.environ["MT5_PASSWORD"] = "pw"
os.environ["MT5_SERVER"] = "Demo-Server"
os.environ["MT5_BRIDGE_SECRET"] = "test-secret"


class _Position(NamedTuple):
    ticket: int
    symbol: str
    type: int
    volume: float
    sl: float = 0.0
    tp: float = 0.0


class _Order(NamedTuple):
    ticket: int
    symbol: str
    type: int
    volume: float


class _Tick(NamedTuple):
    bid: float
    ask: float


class _SendResult(NamedTuple):
    retcode: int
    order: int = 0
    comment: str = ""


class FakeMT5State:
    """Mutable fixture state the fake module's functions read from."""

    def __init__(self) -> None:
        self.connected = True
        self.positions: list[_Position] = []
        self.orders: list[_Order] = []
        self.ticks: dict[str, _Tick] = {}
        # send_result / send_results_by_filling let tests script order_send's outcome.
        self.send_result: Optional[_SendResult] = _SendResult(retcode=10009, order=999)
        self.send_calls: list[dict] = []
        self.last_error_value = (0, "no error")


def _build_fake_module(state: FakeMT5State) -> types.ModuleType:
    m = types.ModuleType("MetaTrader5")

    # Constants — real MT5 numeric values, referenced by name everywhere in
    # app.py so the exact numbers only need to be right here, once.
    m.POSITION_TYPE_BUY = 0
    m.POSITION_TYPE_SELL = 1
    m.ORDER_TYPE_BUY = 0
    m.ORDER_TYPE_SELL = 1
    m.TRADE_ACTION_DEAL = 1
    m.TRADE_ACTION_SLTP = 6
    m.ORDER_TIME_GTC = 0
    m.ORDER_FILLING_IOC = 1
    m.ORDER_FILLING_FOK = 2
    m.ORDER_FILLING_RETURN = 0
    m.TRADE_RETCODE_DONE = 10009

    def terminal_info():
        return object() if state.connected else None

    def initialize(**kwargs):
        state.connected = True
        return True

    def last_error():
        return state.last_error_value

    def positions_get(ticket: Optional[int] = None):
        if ticket is not None:
            return tuple(p for p in state.positions if p.ticket == ticket)
        return tuple(state.positions)

    def orders_get():
        return tuple(state.orders)

    def symbol_select(symbol: str, enable: bool):
        return True

    def symbol_info_tick(symbol: str):
        return state.ticks.get(symbol)

    def order_send(request: dict):
        state.send_calls.append(request)
        return state.send_result

    m.terminal_info = terminal_info
    m.initialize = initialize
    m.last_error = last_error
    m.positions_get = positions_get
    m.orders_get = orders_get
    m.symbol_select = symbol_select
    m.symbol_info_tick = symbol_info_tick
    m.order_send = order_send
    return m


@pytest.fixture
def mt5_state() -> FakeMT5State:
    return FakeMT5State()


@pytest.fixture
def app_module(mt5_state: FakeMT5State):
    """A fresh import of app.py wired to this test's fake MetaTrader5 module."""
    sys.modules["MetaTrader5"] = _build_fake_module(mt5_state)
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    yield module
    sys.modules.pop("app", None)
    sys.modules.pop("MetaTrader5", None)
