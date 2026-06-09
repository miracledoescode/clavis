"""Tests for MetaApiBrokerAdapter and symbol_normalizer.

MetaApi SDK is not installed in CI; the SDK import is intercepted by a fake
injected into sys.modules so every test runs without a real connection.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import asyncio

import pytest

from app.bridge.symbol_normalizer import denormalize, normalize


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
    # Symbol doesn't end with the suffix — return unchanged.
    assert denormalize("EURUSD", ".m") == "EURUSD"


def test_normalize_denormalize_round_trip():
    for suffix in [".m", "m", ".raw"]:
        for sym in ["EURUSD", "XAUUSD", "GBPJPY"]:
            assert denormalize(normalize(sym, suffix), suffix) == sym


# --------------------------------------------------------------------------- #
# Fake MetaApi SDK                                                             #
# --------------------------------------------------------------------------- #
# Injected into sys.modules so MetaApiBrokerAdapter can import it without the
# real package installed.


def _make_fake_sdk(conn_mock: MagicMock) -> None:
    """Wire a fake metaapi_cloud_sdk package around the given connection mock."""
    account = MagicMock()
    account.get_rpc_connection = AsyncMock(return_value=conn_mock)
    account.deploy = AsyncMock()

    account_api = MagicMock()
    account_api.get_account = AsyncMock(return_value=account)

    api_instance = MagicMock()
    api_instance.metatrader_account_api = account_api

    fake_class = MagicMock(return_value=api_instance)

    module = types.ModuleType("metaapi_cloud_sdk")
    module.MetaApi = fake_class  # type: ignore[attr-defined]

    sys.modules["metaapi_cloud_sdk"] = module


def _make_conn(
    positions: list[dict] | None = None,
    orders: list[dict] | None = None,
) -> MagicMock:
    """Create a fake MetaApi RPC connection with terminal_state populated."""
    ts = MagicMock()
    ts.positions = positions or []
    ts.orders = orders or []

    conn = MagicMock()
    conn.terminal_state = ts
    conn.connect = AsyncMock()
    conn.wait_synchronized = AsyncMock()
    conn.create_market_buy_order = AsyncMock(return_value={"positionId": "T1"})
    conn.create_market_sell_order = AsyncMock(return_value={"positionId": "T2"})
    conn.modify_position = AsyncMock()
    conn.close_position = AsyncMock()
    return conn


@pytest.fixture(autouse=True)
def clean_metaapi_module():
    """Remove the fake module after each test so imports stay isolated."""
    yield
    sys.modules.pop("metaapi_cloud_sdk", None)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

run = asyncio.run


def _make_adapter(conn, symbol_suffix=None):
    """Return a MetaApiBrokerAdapter with its internal conn pre-seeded."""
    from app.bridge.broker import MetaApiBrokerAdapter

    adapter = MetaApiBrokerAdapter("tok", "acc-id", symbol_suffix)
    adapter._conn = conn  # skip real connection
    return adapter


# --------------------------------------------------------------------------- #
# get_open_positions                                                           #
# --------------------------------------------------------------------------- #


def test_get_open_positions_maps_buy():
    raw = {
        "id": "T1",
        "symbol": "EURUSD.m",
        "type": "POSITION_TYPE_BUY",
        "volume": 0.1,
        "clientId": "p1",
    }
    adapter = _make_adapter(_make_conn(positions=[raw]), symbol_suffix=".m")
    positions = run(adapter.get_open_positions())

    assert len(positions) == 1
    p = positions[0]
    assert p.position_id == "T1"
    assert p.symbol == "EURUSD"     # suffix stripped
    assert p.direction == "long"
    assert p.volume == 0.1
    assert p.client_id == "p1"


def test_get_open_positions_maps_sell():
    raw = {"id": "T2", "symbol": "GBPUSD", "type": "POSITION_TYPE_SELL", "volume": 0.2}
    adapter = _make_adapter(_make_conn(positions=[raw]))
    positions = run(adapter.get_open_positions())
    assert positions[0].direction == "short"


def test_get_open_positions_empty():
    adapter = _make_adapter(_make_conn())
    assert run(adapter.get_open_positions()) == []


# --------------------------------------------------------------------------- #
# get_working_orders                                                           #
# --------------------------------------------------------------------------- #


def test_get_working_orders_maps_correctly():
    raw = {
        "id": "O1",
        "symbol": "XAUUSD.m",
        "type": "ORDER_TYPE_BUY_LIMIT",
        "volume": 0.05,
        "clientId": "p2",
    }
    adapter = _make_adapter(_make_conn(orders=[raw]), symbol_suffix=".m")
    orders = run(adapter.get_working_orders())

    assert len(orders) == 1
    o = orders[0]
    assert o.order_id == "O1"
    assert o.symbol == "XAUUSD"   # suffix stripped
    assert o.direction == "long"
    assert o.client_id == "p2"


# --------------------------------------------------------------------------- #
# get_position                                                                 #
# --------------------------------------------------------------------------- #


def test_get_position_found():
    raw = {"id": "T9", "symbol": "EURUSD", "type": "POSITION_TYPE_BUY", "volume": 0.1}
    adapter = _make_adapter(_make_conn(positions=[raw]))
    p = run(adapter.get_position("T9"))
    assert p is not None
    assert p.position_id == "T9"


def test_get_position_not_found():
    adapter = _make_adapter(_make_conn())
    assert run(adapter.get_position("MISSING")) is None


# --------------------------------------------------------------------------- #
# place_order                                                                  #
# --------------------------------------------------------------------------- #


def test_place_order_long_sends_buy_with_suffix():
    conn = _make_conn()
    conn.create_market_buy_order = AsyncMock(return_value={"positionId": "T3"})
    adapter = _make_adapter(conn, symbol_suffix=".m")

    pos = run(
        adapter.place_order(
            client_id="prop-abc",
            symbol="EURUSD",
            direction="long",
            volume=0.1,
            stop_loss=1.0800,
            take_profit=[1.0950],
        )
    )

    # Broker call used the suffixed symbol.
    conn.create_market_buy_order.assert_called_once()
    call_args = conn.create_market_buy_order.call_args
    assert call_args.args[0] == "EURUSD.m"
    assert call_args.args[3] == 1.0950        # first TP
    assert call_args.args[4] == {"clientId": "prop-abc"}

    # Returned position carries the canonical (unsuffixed) symbol.
    assert pos.symbol == "EURUSD"
    assert pos.client_id == "prop-abc"
    assert pos.position_id == "T3"


def test_place_order_short_sends_sell():
    conn = _make_conn()
    conn.create_market_sell_order = AsyncMock(return_value={"positionId": "T4"})
    adapter = _make_adapter(conn)

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
    conn.create_market_sell_order.assert_called_once()
    conn.create_market_buy_order.assert_not_called()


def test_place_order_uses_first_tp_when_multiple():
    conn = _make_conn()
    adapter = _make_adapter(conn)
    run(
        adapter.place_order(
            client_id="p",
            symbol="EURUSD",
            direction="long",
            volume=0.1,
            stop_loss=1.08,
            take_profit=[1.09, 1.10, 1.11],
        )
    )
    call_args = conn.create_market_buy_order.call_args
    assert call_args.args[3] == 1.09  # first TP only


def test_place_order_rejects_zero_stop_loss():
    adapter = _make_adapter(_make_conn())
    with pytest.raises(ValueError, match="stop_loss"):
        run(
            adapter.place_order(
                client_id="p",
                symbol="EURUSD",
                direction="long",
                volume=0.1,
                stop_loss=0.0,
                take_profit=[1.10],
            )
        )


def test_place_order_rejects_empty_take_profit():
    adapter = _make_adapter(_make_conn())
    with pytest.raises(ValueError, match="take_profit"):
        run(
            adapter.place_order(
                client_id="p",
                symbol="EURUSD",
                direction="long",
                volume=0.1,
                stop_loss=1.08,
                take_profit=[],
            )
        )


# --------------------------------------------------------------------------- #
# modify_position / close_position                                             #
# --------------------------------------------------------------------------- #


def test_modify_position_delegates_to_metaapi():
    conn = _make_conn()
    adapter = _make_adapter(conn)
    run(adapter.modify_position(position_id="T5", stop_loss=1.07, take_profit=1.12))
    conn.modify_position.assert_called_once_with("T5", 1.07, 1.12)


def test_close_position_delegates_to_metaapi():
    conn = _make_conn()
    adapter = _make_adapter(conn)
    run(adapter.close_position("T6"))
    conn.close_position.assert_called_once_with("T6")


# --------------------------------------------------------------------------- #
# Protocol conformance                                                         #
# --------------------------------------------------------------------------- #


def test_metaapi_adapter_satisfies_protocol():
    from app.bridge.broker import BrokerAdapter, MetaApiBrokerAdapter

    assert isinstance(MetaApiBrokerAdapter("t", "a"), BrokerAdapter)


def test_not_implemented_adapter_satisfies_protocol():
    from app.bridge.broker import BrokerAdapter, NotImplementedBrokerAdapter

    assert isinstance(NotImplementedBrokerAdapter(), BrokerAdapter)
