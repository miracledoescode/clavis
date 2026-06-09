"""Broker adapter — MetaApi implementation.

INTERNAL infrastructure: no public ingress.
Path: Frontend -> FastAPI -> Bridge (CLAUDE.md).

SAFETY INVARIANT: SL and TP are ALWAYS set on the order at the broker.
``place_order`` enforces this at runtime (not just via the type signature) so
an outage never leaves an unmanaged position.

The MetaApi RPC connection is created lazily on the first call and reused.
Symbols are normalised through ``symbol_normalizer`` so Clavis canonical names
(e.g. ``EURUSD``) are transparently mapped to broker-specific names
(e.g. ``EURUSD.m``) on send and stripped on read.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from app.bridge.symbol_normalizer import denormalize, normalize
from app.engine.live_state import BrokerOrder, BrokerPosition, Side

logger = logging.getLogger(__name__)

# MetaApi position/order type strings that represent a BUY direction.
_BUY_TYPES = frozenset(
    {
        "POSITION_TYPE_BUY",
        "ORDER_TYPE_BUY_LIMIT",
        "ORDER_TYPE_BUY_STOP",
        "ORDER_TYPE_BUY_STOP_LIMIT",
    }
)


# --------------------------------------------------------------------------- #
# Protocol (the engine's view of the broker)                                  #
# --------------------------------------------------------------------------- #


@runtime_checkable
class BrokerAdapter(Protocol):
    """What the engine needs from the broker. ``MetaApiBrokerAdapter`` satisfies this."""

    async def get_open_positions(self) -> list[BrokerPosition]: ...
    async def get_working_orders(self) -> list[BrokerOrder]: ...
    async def get_position(self, position_id: str) -> Optional[BrokerPosition]: ...

    async def place_order(
        self,
        *,
        client_id: str,          # idempotency key (== proposal_id); set on the broker order
        symbol: str,             # Clavis canonical (e.g. "EURUSD")
        direction: Side,
        volume: float,
        stop_loss: float,        # required — SL MUST live at the broker
        take_profit: list[float],  # required — TP MUST live at the broker; first element used
    ) -> BrokerPosition: ...

    async def modify_position(
        self,
        *,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> None: ...

    async def close_position(self, position_id: str) -> None: ...


# --------------------------------------------------------------------------- #
# Stub (replaced by MetaApiBrokerAdapter once MetaApi credentials are wired)  #
# --------------------------------------------------------------------------- #


class NotImplementedBrokerAdapter:
    """Placeholder until MetaApi credentials are available in the environment."""

    _MSG = "BrokerAdapter not wired — set METAAPI_TOKEN and METAAPI_ACCOUNT_ID."

    async def get_open_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError(self._MSG)

    async def get_working_orders(self) -> list[BrokerOrder]:
        raise NotImplementedError(self._MSG)

    async def get_position(self, position_id: str) -> Optional[BrokerPosition]:
        raise NotImplementedError(self._MSG)

    async def place_order(
        self,
        *,
        client_id: str,
        symbol: str,
        direction: Side,
        volume: float,
        stop_loss: float,
        take_profit: list[float],
    ) -> BrokerPosition:
        raise NotImplementedError(self._MSG)

    async def modify_position(
        self,
        *,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> None:
        raise NotImplementedError(self._MSG)

    async def close_position(self, position_id: str) -> None:
        raise NotImplementedError(self._MSG)


# --------------------------------------------------------------------------- #
# Live implementation                                                          #
# --------------------------------------------------------------------------- #


class MetaApiBrokerAdapter:
    """Live MetaApi implementation of ``BrokerAdapter``.

    One instance per account; the RPC connection is created lazily on the first
    call and reused for the process lifetime.

    Args:
        token:         MetaApi API token.
        account_id:    MetaApi account UUID.
        symbol_suffix: Broker-specific suffix (e.g. ``".m"`` for Exness /
                       Justmarkets). Applied when writing symbols to the broker;
                       stripped when reading them back.
    """

    def __init__(
        self,
        token: str,
        account_id: str,
        symbol_suffix: str | None = None,
    ) -> None:
        self._token = token
        self._account_id = account_id
        self._symbol_suffix = symbol_suffix
        self._conn = None  # lazy — created in _connection()

    # -- connection lifecycle ------------------------------------------------ #

    async def _connection(self):
        if self._conn is not None:
            return self._conn
        try:
            from metaapi_cloud_sdk import MetaApi  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "metaapi-cloud-sdk is not installed. "
                "Add it to requirements.txt and rebuild the Docker image."
            ) from exc
        api = MetaApi(self._token)
        account = await api.metatrader_account_api.get_account(self._account_id)
        conn = await account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized({"timeoutInSeconds": 60})
        self._conn = conn
        logger.info("MetaApi RPC connection established for account %s", self._account_id)
        return self._conn

    # -- private helpers ----------------------------------------------------- #

    def _broker_symbol(self, canonical: str) -> str:
        return normalize(canonical, self._symbol_suffix)

    def _canonical_symbol(self, broker_symbol: str) -> str:
        return denormalize(broker_symbol, self._symbol_suffix)

    def _direction(self, type_str: str) -> Side:
        return "long" if type_str in _BUY_TYPES else "short"

    def _map_position(self, raw: dict) -> BrokerPosition:
        return BrokerPosition(
            position_id=str(raw["id"]),
            symbol=self._canonical_symbol(raw.get("symbol", "")),
            direction=self._direction(raw.get("type", "")),
            volume=float(raw["volume"]),
            client_id=raw.get("clientId"),
        )

    def _map_order(self, raw: dict) -> BrokerOrder:
        return BrokerOrder(
            order_id=str(raw["id"]),
            symbol=self._canonical_symbol(raw.get("symbol", "")),
            direction=self._direction(raw.get("type", "")),
            volume=float(raw["volume"]),
            client_id=raw.get("clientId"),
        )

    # -- BrokerAdapter interface --------------------------------------------- #

    async def get_open_positions(self) -> list[BrokerPosition]:
        conn = await self._connection()
        return [self._map_position(p) for p in (conn.terminal_state.positions or [])]

    async def get_working_orders(self) -> list[BrokerOrder]:
        conn = await self._connection()
        return [self._map_order(o) for o in (conn.terminal_state.orders or [])]

    async def get_position(self, position_id: str) -> Optional[BrokerPosition]:
        positions = await self.get_open_positions()
        return next((p for p in positions if p.position_id == position_id), None)

    async def place_order(
        self,
        *,
        client_id: str,
        symbol: str,
        direction: Side,
        volume: float,
        stop_loss: float,
        take_profit: list[float],
    ) -> BrokerPosition:
        # Runtime guard — the constitution requires SL/TP at the broker on every order.
        if not stop_loss:
            raise ValueError("place_order: stop_loss is required — SL must live at the broker")
        if not take_profit:
            raise ValueError("place_order: take_profit is required — TP must live at the broker")

        conn = await self._connection()
        broker_symbol = self._broker_symbol(symbol)
        tp = take_profit[0]  # MetaApi takes a single TP value; use the first target
        options = {"clientId": client_id}

        if direction == "long":
            result = await conn.create_market_buy_order(
                broker_symbol, volume, stop_loss, tp, options
            )
        else:
            result = await conn.create_market_sell_order(
                broker_symbol, volume, stop_loss, tp, options
            )

        # Market orders fill near-instantly; positionId is set in the result.
        position_id = result.get("positionId") or result.get("orderId", "")
        return BrokerPosition(
            position_id=position_id,
            symbol=symbol,
            direction=direction,
            volume=volume,
            client_id=client_id,
        )

    async def modify_position(
        self,
        *,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> None:
        conn = await self._connection()
        await conn.modify_position(position_id, stop_loss, take_profit)

    async def close_position(self, position_id: str) -> None:
        conn = await self._connection()
        await conn.close_position(position_id)
