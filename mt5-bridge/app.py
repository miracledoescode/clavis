"""MT5 bridge — a thin HTTP wrapper around MetaQuotes' free MetaTrader5 Python
package, run on a Windows machine next to the actual MT5 terminal.

WHY THIS EXISTS: the `MetaTrader5` package only ships Windows wheels and talks
to a terminal running on the SAME machine over local IPC — it cannot be
imported into the main Clavis engine (Linux/Docker/Railway). This service is
the self-hosted, subscription-free alternative to MetaApi: it runs where the
terminal runs, and the main engine (`backend/app/bridge/broker.py` /
`price_feed.py`) talks to it over HTTP instead.

SAFETY (CLAUDE.md "The MT5 bridge is internal infrastructure. It has no
public ingress."): this service must NEVER be exposed to the public internet.
Run it behind a firewall / private network / VPN (e.g. Tailscale) between it
and the Clavis engine, with only that private address reachable. The bearer
secret below is defense-in-depth, not a substitute for network isolation.

Every order-placing call enforces SL/TP, matching the engine's own runtime
guard in bridge/broker.py — an outage must never leave an unmanaged position.
"""
from __future__ import annotations

import hashlib
import os
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

import MetaTrader5 as mt5

MT5_LOGIN = os.environ["MT5_LOGIN"]
MT5_PASSWORD = os.environ["MT5_PASSWORD"]
MT5_SERVER = os.environ["MT5_SERVER"]
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH") or None
BRIDGE_SECRET = os.environ["MT5_BRIDGE_SECRET"]
DEVIATION_POINTS = int(os.getenv("MT5_DEVIATION_POINTS", "20"))

app = FastAPI(title="Clavis MT5 Bridge")

_FILLING_MODES_TO_TRY = ("IOC", "FOK", "RETURN")


def _require_secret(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != BRIDGE_SECRET:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")


def _ensure_initialized() -> None:
    """Connects (or reconnects) to the local terminal. Idempotent — mt5.initialize()
    is a no-op if already connected, and terminal_info() detects a dropped link."""
    if mt5.terminal_info() is not None:
        return
    kwargs = dict(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)
    if MT5_TERMINAL_PATH:
        kwargs["path"] = MT5_TERMINAL_PATH
    if not mt5.initialize(**kwargs):
        code, desc = mt5.last_error()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"MT5 initialize failed: {code} {desc}"
        )


def _direction_of(position_or_order_type: int) -> Literal["long", "short"]:
    return "long" if position_or_order_type == mt5.POSITION_TYPE_BUY else "short"


# --------------------------------------------------------------------------- #
# Schemas                                                                      #
# --------------------------------------------------------------------------- #


class PositionOut(BaseModel):
    position_id: str
    symbol: str
    direction: Literal["long", "short"]
    volume: float


class OrderOut(BaseModel):
    order_id: str
    symbol: str
    direction: Literal["long", "short"]
    volume: float


class TickOut(BaseModel):
    symbol: str
    bid: float
    ask: float


class PlaceOrderIn(BaseModel):
    client_id: str
    symbol: str
    direction: Literal["long", "short"]
    volume: float
    stop_loss: float
    take_profit: float  # bridge takes a single TP price; the engine picks the first leg


class ModifyPositionIn(BaseModel):
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #


@app.get("/health")
async def health() -> dict:
    """No auth required — a plain liveness probe."""
    return {"status": "ok"}


@app.get("/positions", response_model=list[PositionOut], dependencies=[Depends(_require_secret)])
async def get_positions() -> list[PositionOut]:
    _ensure_initialized()
    positions = mt5.positions_get() or ()
    return [
        PositionOut(
            position_id=str(p.ticket),
            symbol=p.symbol,
            direction=_direction_of(p.type),
            volume=p.volume,
        )
        for p in positions
    ]


@app.get("/orders", response_model=list[OrderOut], dependencies=[Depends(_require_secret)])
async def get_orders() -> list[OrderOut]:
    _ensure_initialized()
    orders = mt5.orders_get() or ()
    return [
        OrderOut(
            order_id=str(o.ticket),
            symbol=o.symbol,
            direction=_direction_of(o.type),
            volume=o.volume,
        )
        for o in orders
    ]


@app.get("/tick", response_model=TickOut, dependencies=[Depends(_require_secret)])
async def get_tick(symbol: str) -> TickOut:
    _ensure_initialized()
    mt5.symbol_select(symbol, True)  # must be in Market Watch for tick data
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No tick data for {symbol!r}")
    return TickOut(symbol=symbol, bid=tick.bid, ask=tick.ask)


@app.post("/orders", response_model=PositionOut, dependencies=[Depends(_require_secret)])
async def place_order(req: PlaceOrderIn) -> PositionOut:
    """Places a market order with SL/TP set on the order itself.

    NOTE on idempotency: unlike MetaApi, the MT5 terminal's `comment` field is
    unreliable for exact client-id round-tripping (brokers commonly truncate it
    to well under its documented 31-char limit), so a full proposal_id UUID
    won't survive intact. This endpoint tags a short hash of client_id into the
    comment for diagnostics only — it is NOT a broker-side duplicate-order
    guard. The real idempotency guard is Clavis's own pre-send check
    (engine/idempotency.py + the Redis-backed used-keys set), which runs
    BEFORE this endpoint is ever called.
    """
    _ensure_initialized()
    if not req.stop_loss:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "stop_loss is required")
    if not req.take_profit:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "take_profit is required")

    mt5.symbol_select(req.symbol, True)
    tick = mt5.symbol_info_tick(req.symbol)
    if tick is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No tick data for {req.symbol!r}")

    order_type = mt5.ORDER_TYPE_BUY if req.direction == "long" else mt5.ORDER_TYPE_SELL
    price = tick.ask if req.direction == "long" else tick.bid
    comment = hashlib.sha1(req.client_id.encode()).hexdigest()[:16]

    result = None
    for mode_name in _FILLING_MODES_TO_TRY:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": req.symbol,
            "volume": req.volume,
            "type": order_type,
            "price": price,
            "sl": req.stop_loss,
            "tp": req.take_profit,
            "deviation": DEVIATION_POINTS,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": getattr(mt5, f"ORDER_FILLING_{mode_name}"),
        }
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            break
    else:
        code = result.retcode if result is not None else None
        comment_out = result.comment if result is not None else mt5.last_error()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"order_send failed: retcode={code} {comment_out}"
        )

    return PositionOut(
        position_id=str(result.order),
        symbol=req.symbol,
        direction=req.direction,
        volume=req.volume,
    )


@app.post(
    "/positions/{position_id}/modify",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_require_secret)],
)
async def modify_position(position_id: str, req: ModifyPositionIn) -> None:
    _ensure_initialized()
    ticket = int(position_id)
    positions = mt5.positions_get(ticket=ticket) or ()
    if not positions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No open position {position_id!r}")
    current = positions[0]

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": current.symbol,
        "sl": req.stop_loss if req.stop_loss is not None else current.sl,
        "tp": req.take_profit if req.take_profit is not None else current.tp,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result is not None else None
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"modify failed: retcode={code}")


@app.post(
    "/positions/{position_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_require_secret)],
)
async def close_position(position_id: str) -> None:
    _ensure_initialized()
    ticket = int(position_id)
    positions = mt5.positions_get(ticket=ticket) or ()
    if not positions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No open position {position_id!r}")
    current = positions[0]

    closing_type = (
        mt5.ORDER_TYPE_SELL if current.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    )
    tick = mt5.symbol_info_tick(current.symbol)
    price = tick.bid if closing_type == mt5.ORDER_TYPE_SELL else tick.ask

    result = None
    for mode_name in _FILLING_MODES_TO_TRY:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": current.symbol,
            "volume": current.volume,
            "type": closing_type,
            "price": price,
            "deviation": DEVIATION_POINTS,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": getattr(mt5, f"ORDER_FILLING_{mode_name}"),
        }
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            return
    code = result.retcode if result is not None else None
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"close failed: retcode={code}")
