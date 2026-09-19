"""Tests for MT5BridgeBrokerAdapter and symbol_normalizer.

Uses httpx.MockTransport to stand in for the mt5-bridge service, so the
adapter's request/response shapes are verified without a real bridge or
network (same pattern as tests/test_copilot.py).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.bridge.broker import BrokerAdapter, MT5BridgeBrokerAdapter, NotImplementedBrokerAdapter
from app.bridge.symbol_normalizer import denormalize, normalize

run = asyncio.run


# --------------------------------------------------------------------------- #
# symbol_normalizer                                                            #
# --------------------------------------------------------------------------- #


def test_normalize_applies_dot_suffix():
    assert normalize("EURUSD", ".m") == "EURUSD.m"


def test_normalize_adds_leading_dot_when_missing():
    assert normalize("EURUSD", "m") == "EURUSD.m"


def test_normalize_no_suffix_is_identity():
    assert normalize("EURUSD") == "EURUSD"
    assert normalize("EURUSD", None) == "EURUSD"
    assert normalize("EURUSD", "") == "EURUSD"


def test_denormalize_strips_suffix():
    assert denormalize("EURUSD.m", ".m") == "EURUSD"


def test_denormalize_adds_dot_when_missing():
    assert denormalize("EURUSD.m", "m") == "EURUSD"


def test_denormalize_no_suffix_is_identity():
    assert denormalize("EURUSD.m") == "EURUSD.m"
    assert denormalize("EURUSD.m", None) == "EURUSD.m"


def test_denormalize_noop_when_suffix_absent():
    assert denormalize("EURUSD", ".m") == "EURUSD"


def test_normalize_denormalize_round_trip():
    for suffix in [".m", "m", ".raw"]:
        for sym in ["EURUSD", "XAUUSD", "GBPJPY"]:
            assert denormalize(normalize(sym, suffix), suffix) == sym


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _adapter(handler, symbol_suffix=None) -> MT5BridgeBrokerAdapter:
    client = httpx.AsyncClient(base_url="http://bridge.test", transport=httpx.MockTransport(handler))
    return MT5BridgeBrokerAdapter("http://bridge.test", "secret", symbol_suffix, client=client)


def test_default_client_sends_bearer_secret():
    """Exercises the adapter's OWN client construction (not the test helper's
    injected one), which is what actually sets the Authorization header."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[])

    adapter = MT5BridgeBrokerAdapter("http://bridge.test", "secret")
    adapter._client._transport = httpx.MockTransport(handler)  # swap in the mock transport

    run(adapter.get_open_positions())
    assert captured["auth"] == "Bearer secret"


# --------------------------------------------------------------------------- #
# get_open_positions / get_working_orders / get_position                      #
# --------------------------------------------------------------------------- #


def test_get_open_positions_maps_and_denormalizes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/positions"
        return httpx.Response(
            200,
            json=[
                {"position_id": "1", "symbol": "EURUSD.m", "direction": "long", "volume": 0.1},
            ],
        )

    adapter = _adapter(handler, symbol_suffix=".m")
    positions = run(adapter.get_open_positions())

    assert len(positions) == 1
    assert positions[0].position_id == "1"
    assert positions[0].symbol == "EURUSD"  # suffix stripped
    assert positions[0].direction == "long"
    assert positions[0].volume == 0.1


def test_get_open_positions_empty():
    adapter = _adapter(lambda r: httpx.Response(200, json=[]))
    assert run(adapter.get_open_positions()) == []


def test_get_working_orders_maps_correctly():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/orders"
        return httpx.Response(
            200,
            json=[{"order_id": "5", "symbol": "XAUUSD.m", "direction": "long", "volume": 0.05}],
        )

    adapter = _adapter(handler, symbol_suffix=".m")
    orders = run(adapter.get_working_orders())

    assert orders[0].order_id == "5"
    assert orders[0].symbol == "XAUUSD"


def test_get_position_found():
    adapter = _adapter(
        lambda r: httpx.Response(
            200, json=[{"position_id": "T9", "symbol": "EURUSD", "direction": "long", "volume": 0.1}]
        )
    )
    p = run(adapter.get_position("T9"))
    assert p is not None
    assert p.position_id == "T9"


def test_get_position_not_found():
    adapter = _adapter(lambda r: httpx.Response(200, json=[]))
    assert run(adapter.get_position("MISSING")) is None


# --------------------------------------------------------------------------- #
# place_order                                                                  #
# --------------------------------------------------------------------------- #


def test_place_order_sends_suffixed_symbol_and_first_tp():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/orders"
        body = json.loads(request.content)
        captured["body"] = body
        return httpx.Response(
            200, json={"position_id": "T3", "symbol": body["symbol"], "direction": "long", "volume": 0.1}
        )

    adapter = _adapter(handler, symbol_suffix=".m")
    pos = run(
        adapter.place_order(
            client_id="prop-abc",
            symbol="EURUSD",
            direction="long",
            volume=0.1,
            stop_loss=1.0800,
            take_profit=[1.0950, 1.10],
        )
    )

    body = captured["body"]
    assert body["symbol"] == "EURUSD.m"
    assert body["take_profit"] == 1.0950  # first leg only
    assert body["client_id"] == "prop-abc"
    # Returned position carries the canonical (unsuffixed) symbol.
    assert pos.symbol == "EURUSD"
    assert pos.client_id == "prop-abc"
    assert pos.position_id == "T3"


def test_place_order_short_direction():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["direction"] == "short"
        return httpx.Response(
            200, json={"position_id": "T4", "symbol": "GBPUSD", "direction": "short", "volume": 0.2}
        )

    adapter = _adapter(handler)
    run(
        adapter.place_order(
            client_id="prop-xyz",
            symbol="GBPUSD",
            direction="short",
            volume=0.2,
            stop_loss=1.3000,
            take_profit=[1.2800],
        )
    )


def test_place_order_rejects_zero_stop_loss():
    adapter = _adapter(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="stop_loss"):
        run(
            adapter.place_order(
                client_id="p", symbol="EURUSD", direction="long", volume=0.1,
                stop_loss=0.0, take_profit=[1.10],
            )
        )


def test_place_order_rejects_empty_take_profit():
    adapter = _adapter(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="take_profit"):
        run(
            adapter.place_order(
                client_id="p", symbol="EURUSD", direction="long", volume=0.1,
                stop_loss=1.08, take_profit=[],
            )
        )


def test_place_order_raises_on_bridge_error():
    adapter = _adapter(lambda r: httpx.Response(502, json={"detail": "order_send failed"}))
    with pytest.raises(httpx.HTTPStatusError):
        run(
            adapter.place_order(
                client_id="p", symbol="EURUSD", direction="long", volume=0.1,
                stop_loss=1.08, take_profit=[1.10],
            )
        )


# --------------------------------------------------------------------------- #
# modify_position / close_position                                            #
# --------------------------------------------------------------------------- #


def test_modify_position_posts_to_bridge():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/positions/T5/modify"
        captured["body"] = json.loads(request.content)
        return httpx.Response(204)

    adapter = _adapter(handler)
    run(adapter.modify_position(position_id="T5", stop_loss=1.07, take_profit=1.12))
    assert captured["body"] == {"stop_loss": 1.07, "take_profit": 1.12}


def test_close_position_posts_to_bridge():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/positions/T6/close"
        return httpx.Response(204)

    adapter = _adapter(handler)
    run(adapter.close_position("T6"))


# --------------------------------------------------------------------------- #
# Protocol conformance                                                        #
# --------------------------------------------------------------------------- #


def test_mt5_bridge_adapter_satisfies_protocol():
    assert isinstance(MT5BridgeBrokerAdapter("http://x", "s"), BrokerAdapter)


def test_not_implemented_adapter_satisfies_protocol():
    assert isinstance(NotImplementedBrokerAdapter(), BrokerAdapter)
