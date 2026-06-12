"""Tests for MetaApiPriceFeed.

MetaApi SDK is not installed in CI; the SDK import is intercepted by a fake
injected into sys.modules so every test runs without a real connection
(same technique as tests/test_broker.py).
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bridge.price_feed import MetaApiPriceFeed, _PriceListener
from app.engine.agent_loop import Tick

run = asyncio.run


# --------------------------------------------------------------------------- #
# _PriceListener                                                               #
# --------------------------------------------------------------------------- #


def test_price_listener_pushes_tick_with_denormalized_symbol():
    queue: asyncio.Queue[Tick] = asyncio.Queue()
    listener = _PriceListener(queue, symbol_suffix=".m")

    run(listener.on_symbol_price_updated("0", {"symbol": "EURUSD.m", "bid": 1.1000, "ask": 1.1002}))

    tick = queue.get_nowait()
    assert tick.symbol == "EURUSD"  # suffix stripped
    assert tick.bid == 1.1000
    assert tick.ask == 1.1002


def test_price_listener_no_suffix_is_identity():
    queue: asyncio.Queue[Tick] = asyncio.Queue()
    listener = _PriceListener(queue)

    run(listener.on_symbol_price_updated("0", {"symbol": "GBPUSD", "bid": 1.27, "ask": 1.2702}))

    tick = queue.get_nowait()
    assert tick.symbol == "GBPUSD"


# --------------------------------------------------------------------------- #
# Fake MetaApi SDK                                                             #
# --------------------------------------------------------------------------- #


def _make_fake_sdk(conn_mock: MagicMock) -> None:
    account = MagicMock()
    account.get_streaming_connection = AsyncMock(return_value=conn_mock)

    account_api = MagicMock()
    account_api.get_account = AsyncMock(return_value=account)

    api_instance = MagicMock()
    api_instance.metatrader_account_api = account_api

    fake_class = MagicMock(return_value=api_instance)

    module = types.ModuleType("metaapi_cloud_sdk")
    module.MetaApi = fake_class  # type: ignore[attr-defined]
    module.SynchronizationListener = object  # type: ignore[attr-defined]

    sys.modules["metaapi_cloud_sdk"] = module


def _make_conn() -> MagicMock:
    conn = MagicMock()
    conn.add_synchronization_listener = MagicMock()
    conn.connect = AsyncMock()
    conn.wait_synchronized = AsyncMock()
    conn.subscribe_to_market_data = AsyncMock()
    conn.close = AsyncMock()
    return conn


@pytest.fixture(autouse=True)
def clean_metaapi_module():
    yield
    sys.modules.pop("metaapi_cloud_sdk", None)


# --------------------------------------------------------------------------- #
# connect / subscribe                                                          #
# --------------------------------------------------------------------------- #


def test_connect_establishes_streaming_connection():
    conn = _make_conn()
    _make_fake_sdk(conn)

    feed = MetaApiPriceFeed("tok", "acc-id")
    run(feed.connect())

    conn.add_synchronization_listener.assert_called_once()
    conn.connect.assert_awaited_once()
    conn.wait_synchronized.assert_awaited_once()


def test_connect_is_idempotent():
    conn = _make_conn()
    _make_fake_sdk(conn)

    feed = MetaApiPriceFeed("tok", "acc-id")
    run(feed.connect())
    run(feed.connect())

    conn.connect.assert_awaited_once()


def test_subscribe_normalizes_symbols_with_suffix():
    conn = _make_conn()
    _make_fake_sdk(conn)

    feed = MetaApiPriceFeed("tok", "acc-id", symbol_suffix=".m")
    run(feed.connect())
    run(feed.subscribe({"EURUSD"}))

    conn.subscribe_to_market_data.assert_awaited_once_with("EURUSD.m")


def test_subscribe_without_connect_raises():
    feed = MetaApiPriceFeed("tok", "acc-id")
    with pytest.raises(RuntimeError, match="connect"):
        run(feed.subscribe({"EURUSD"}))


# --------------------------------------------------------------------------- #
# ticks / aclose                                                               #
# --------------------------------------------------------------------------- #


def test_ticks_yields_queued_ticks():
    feed = MetaApiPriceFeed("tok", "acc-id")
    expected = Tick(symbol="EURUSD", bid=1.1, ask=1.1002, timestamp=datetime.now(timezone.utc))
    feed._queue.put_nowait(expected)

    async def first_tick():
        async for tick in feed.ticks():
            return tick

    assert run(first_tick()) is expected


def test_aclose_closes_connection():
    conn = _make_conn()
    _make_fake_sdk(conn)

    feed = MetaApiPriceFeed("tok", "acc-id")
    run(feed.connect())
    run(feed.aclose())

    conn.close.assert_awaited_once()
