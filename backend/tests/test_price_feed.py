"""Tests for MT5BridgePriceFeed.

Uses httpx.MockTransport to stand in for the mt5-bridge service. The polling
loop itself isn't exercised end-to-end (it just sleeps and repeats); instead
`_poll_one` — the pure per-symbol unit — is called directly, which is what
the loop calls on every tick.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.bridge.price_feed import MT5BridgePriceFeed

run = asyncio.run


def _feed(handler, symbol_suffix=None) -> MT5BridgePriceFeed:
    client = httpx.AsyncClient(base_url="http://bridge.test", transport=httpx.MockTransport(handler))
    return MT5BridgePriceFeed("http://bridge.test", "secret", symbol_suffix, client=client)


def test_poll_one_normalizes_symbol_and_queues_tick():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["symbol"] = request.url.params["symbol"]
        return httpx.Response(200, json={"symbol": "EURUSD.m", "bid": 1.1000, "ask": 1.1002})

    feed = _feed(handler, symbol_suffix=".m")
    run(feed._poll_one("EURUSD"))

    assert captured["symbol"] == "EURUSD.m"
    tick = feed._queue.get_nowait()
    assert tick.symbol == "EURUSD"
    assert tick.bid == 1.1000
    assert tick.ask == 1.1002


def test_poll_one_skips_unchanged_quote():
    feed = _feed(lambda r: httpx.Response(200, json={"symbol": "EURUSD", "bid": 1.1, "ask": 1.1002}))

    run(feed._poll_one("EURUSD"))
    run(feed._poll_one("EURUSD"))  # same quote again

    assert feed._queue.qsize() == 1  # second poll produced no new tick


def test_poll_one_pushes_on_change():
    quotes = iter([
        {"symbol": "EURUSD", "bid": 1.1000, "ask": 1.1002},
        {"symbol": "EURUSD", "bid": 1.1005, "ask": 1.1007},
    ])
    feed = _feed(lambda r: httpx.Response(200, json=next(quotes)))

    run(feed._poll_one("EURUSD"))
    run(feed._poll_one("EURUSD"))

    assert feed._queue.qsize() == 2


def test_poll_one_swallows_http_errors():
    feed = _feed(lambda r: httpx.Response(404))
    run(feed._poll_one("EURUSD"))  # must not raise
    assert feed._queue.qsize() == 0


def test_subscribe_starts_poll_task():
    feed = _feed(lambda r: httpx.Response(200, json={"symbol": "EURUSD", "bid": 1.1, "ask": 1.1002}))

    async def scenario():
        assert feed._poll_task is None
        await feed.subscribe({"EURUSD"})
        assert feed._poll_task is not None
        await feed.aclose()

    run(scenario())


def test_ticks_yields_queued_ticks():
    from datetime import datetime, timezone
    from app.engine.agent_loop import Tick

    feed = _feed(lambda r: httpx.Response(200, json={}))
    expected = Tick(symbol="EURUSD", bid=1.1, ask=1.1002, timestamp=datetime.now(timezone.utc))
    feed._queue.put_nowait(expected)

    async def first_tick():
        async for tick in feed.ticks():
            return tick

    assert run(first_tick()) is expected


def test_aclose_cancels_poll_task_and_closes_client():
    feed = _feed(lambda r: httpx.Response(200, json={"symbol": "EURUSD", "bid": 1.1, "ask": 1.1002}))

    async def scenario():
        await feed.subscribe({"EURUSD"})
        await feed.aclose()

    run(scenario())
    assert feed._poll_task is None
    assert feed._client.is_closed
