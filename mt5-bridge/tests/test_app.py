from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import _Order, _Position, _SendResult, _Tick

AUTH = {"Authorization": "Bearer test-secret"}


def test_health_requires_no_auth(app_module):
    client = TestClient(app_module.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_missing_auth_rejected(app_module):
    client = TestClient(app_module.app)
    resp = client.get("/positions")
    assert resp.status_code == 401


def test_wrong_secret_rejected(app_module):
    client = TestClient(app_module.app)
    resp = client.get("/positions", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# GET /positions, /orders                                                     #
# --------------------------------------------------------------------------- #


def test_get_positions_maps_buy_and_sell(app_module, mt5_state):
    mt5_state.positions = [
        _Position(ticket=1, symbol="EURUSD", type=0, volume=0.1),
        _Position(ticket=2, symbol="GBPUSD", type=1, volume=0.2),
    ]
    client = TestClient(app_module.app)
    resp = client.get("/positions", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body[0] == {
        "position_id": "1", "symbol": "EURUSD", "direction": "long", "volume": 0.1
    }
    assert body[1]["direction"] == "short"


def test_get_positions_empty(app_module):
    client = TestClient(app_module.app)
    resp = client.get("/positions", headers=AUTH)
    assert resp.json() == []


def test_get_orders_maps_correctly(app_module, mt5_state):
    mt5_state.orders = [_Order(ticket=5, symbol="XAUUSD", type=0, volume=0.05)]
    client = TestClient(app_module.app)
    resp = client.get("/orders", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == [
        {"order_id": "5", "symbol": "XAUUSD", "direction": "long", "volume": 0.05}
    ]


# --------------------------------------------------------------------------- #
# GET /tick                                                                    #
# --------------------------------------------------------------------------- #


def test_get_tick_returns_bid_ask(app_module, mt5_state):
    mt5_state.ticks["EURUSD"] = _Tick(bid=1.1000, ask=1.1002)
    client = TestClient(app_module.app)
    resp = client.get("/tick", params={"symbol": "EURUSD"}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"symbol": "EURUSD", "bid": 1.1000, "ask": 1.1002}


def test_get_tick_missing_symbol_404s(app_module):
    client = TestClient(app_module.app)
    resp = client.get("/tick", params={"symbol": "NOPE"}, headers=AUTH)
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# POST /orders                                                                 #
# --------------------------------------------------------------------------- #


def _place_order_body(**overrides) -> dict:
    body = {
        "client_id": "prop-abc",
        "symbol": "EURUSD",
        "direction": "long",
        "volume": 0.1,
        "stop_loss": 1.0800,
        "take_profit": 1.0950,
    }
    body.update(overrides)
    return body


def test_place_order_happy_path(app_module, mt5_state):
    mt5_state.ticks["EURUSD"] = _Tick(bid=1.0899, ask=1.0901)
    mt5_state.send_result = _SendResult(retcode=10009, order=42)
    client = TestClient(app_module.app)

    resp = client.post("/orders", json=_place_order_body(), headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {
        "position_id": "42", "symbol": "EURUSD", "direction": "long", "volume": 0.1
    }
    # SL/TP were carried onto the order_send request itself.
    sent = mt5_state.send_calls[0]
    assert sent["sl"] == 1.0800
    assert sent["tp"] == 1.0950
    assert sent["type"] == app_module.mt5.ORDER_TYPE_BUY


def test_place_order_short_uses_bid_and_sell_type(app_module, mt5_state):
    mt5_state.ticks["GBPUSD"] = _Tick(bid=1.2700, ask=1.2702)
    mt5_state.send_result = _SendResult(retcode=10009, order=7)
    client = TestClient(app_module.app)

    resp = client.post(
        "/orders",
        json=_place_order_body(symbol="GBPUSD", direction="short", stop_loss=1.28, take_profit=1.26),
        headers=AUTH,
    )

    assert resp.status_code == 200
    sent = mt5_state.send_calls[0]
    assert sent["type"] == app_module.mt5.ORDER_TYPE_SELL
    assert sent["price"] == 1.2700  # bid, not ask


def test_place_order_rejects_missing_stop_loss(app_module, mt5_state):
    mt5_state.ticks["EURUSD"] = _Tick(bid=1.0899, ask=1.0901)
    client = TestClient(app_module.app)
    resp = client.post("/orders", json=_place_order_body(stop_loss=0.0), headers=AUTH)
    assert resp.status_code == 400


def test_place_order_rejects_missing_take_profit(app_module, mt5_state):
    mt5_state.ticks["EURUSD"] = _Tick(bid=1.0899, ask=1.0901)
    client = TestClient(app_module.app)
    resp = client.post("/orders", json=_place_order_body(take_profit=0.0), headers=AUTH)
    assert resp.status_code == 400


def test_place_order_no_tick_data_404s(app_module):
    client = TestClient(app_module.app)
    resp = client.post("/orders", json=_place_order_body(symbol="NOPE"), headers=AUTH)
    assert resp.status_code == 404


def test_place_order_retries_across_filling_modes(app_module, mt5_state):
    """First filling mode (IOC) rejected -> retries FOK -> succeeds."""
    mt5_state.ticks["EURUSD"] = _Tick(bid=1.0899, ask=1.0901)
    results = iter([
        _SendResult(retcode=10030, order=0),  # unsupported filling mode
        _SendResult(retcode=10009, order=55),
    ])
    app_module.mt5.order_send = lambda request: (
        mt5_state.send_calls.append(request) or next(results)
    )
    client = TestClient(app_module.app)

    resp = client.post("/orders", json=_place_order_body(), headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["position_id"] == "55"
    assert len(mt5_state.send_calls) == 2
    assert mt5_state.send_calls[0]["type_filling"] == app_module.mt5.ORDER_FILLING_IOC
    assert mt5_state.send_calls[1]["type_filling"] == app_module.mt5.ORDER_FILLING_FOK


def test_place_order_all_filling_modes_fail_502s(app_module, mt5_state):
    mt5_state.ticks["EURUSD"] = _Tick(bid=1.0899, ask=1.0901)
    mt5_state.send_result = _SendResult(retcode=10030, order=0, comment="rejected")
    client = TestClient(app_module.app)

    resp = client.post("/orders", json=_place_order_body(), headers=AUTH)

    assert resp.status_code == 502
    assert len(mt5_state.send_calls) == 3  # tried every filling mode


# --------------------------------------------------------------------------- #
# POST /positions/{id}/modify, /close                                         #
# --------------------------------------------------------------------------- #


def test_modify_position_carries_forward_unspecified_sl_tp(app_module, mt5_state):
    mt5_state.positions = [_Position(ticket=9, symbol="EURUSD", type=0, volume=0.1, sl=1.05, tp=1.12)]
    mt5_state.send_result = _SendResult(retcode=10009)
    client = TestClient(app_module.app)

    resp = client.post("/positions/9/modify", json={"stop_loss": 1.06}, headers=AUTH)

    assert resp.status_code == 204
    sent = mt5_state.send_calls[0]
    assert sent["sl"] == 1.06
    assert sent["tp"] == 1.12  # unspecified -> kept from the current position


def test_modify_position_not_found_404s(app_module):
    client = TestClient(app_module.app)
    resp = client.post("/positions/999/modify", json={"stop_loss": 1.0}, headers=AUTH)
    assert resp.status_code == 404


def test_close_position_sends_opposite_side(app_module, mt5_state):
    mt5_state.positions = [_Position(ticket=3, symbol="EURUSD", type=0, volume=0.1)]
    mt5_state.ticks["EURUSD"] = _Tick(bid=1.09, ask=1.0902)
    mt5_state.send_result = _SendResult(retcode=10009)
    client = TestClient(app_module.app)

    resp = client.post("/positions/3/close", headers=AUTH)

    assert resp.status_code == 204
    sent = mt5_state.send_calls[0]
    assert sent["type"] == app_module.mt5.ORDER_TYPE_SELL  # closing a long
    assert sent["position"] == 3
    assert sent["volume"] == 0.1


def test_close_position_not_found_404s(app_module):
    client = TestClient(app_module.app)
    resp = client.post("/positions/999/close", headers=AUTH)
    assert resp.status_code == 404
