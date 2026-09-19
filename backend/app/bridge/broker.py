"""Broker adapter — self-hosted MT5 bridge implementation.

INTERNAL infrastructure: no public ingress.
Path: Frontend -> FastAPI -> Bridge (CLAUDE.md).

SAFETY INVARIANT: SL and TP are ALWAYS set on the order at the broker.
``place_order`` enforces this at runtime (not just via the type signature) so
an outage never leaves an unmanaged position.

We do NOT use MetaApi (a paid, per-account SaaS). Instead ``mt5-bridge/`` — a
small self-hosted service using MetaQuotes' free ``MetaTrader5`` Python
package — runs on a Windows machine next to the actual MT5 terminal, and this
adapter is its HTTP client. Symbols are normalised through
``symbol_normalizer`` here, on the Clavis side, exactly as before; the bridge
service is symbol-suffix-agnostic and only ever sees/returns whatever string
it's given.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

import httpx

from app.bridge.symbol_normalizer import denormalize, normalize
from app.engine.live_state import BrokerOrder, BrokerPosition, Side

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Protocol (the engine's view of the broker)                                  #
# --------------------------------------------------------------------------- #


@runtime_checkable
class BrokerAdapter(Protocol):
    """What the engine needs from the broker. ``MT5BridgeBrokerAdapter`` satisfies this."""

    async def get_open_positions(self) -> list[BrokerPosition]: ...
    async def get_working_orders(self) -> list[BrokerOrder]: ...
    async def get_position(self, position_id: str) -> Optional[BrokerPosition]: ...

    async def place_order(
        self,
        *,
        client_id: str,          # idempotency key (== proposal_id); see mt5-bridge/README.md
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
# Stub (replaced by MT5BridgeBrokerAdapter once the bridge is deployed)       #
# --------------------------------------------------------------------------- #


class NotImplementedBrokerAdapter:
    """Placeholder until the mt5-bridge service is deployed and configured."""

    _MSG = "BrokerAdapter not wired — set MT5_BRIDGE_URL and MT5_BRIDGE_SECRET."

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


class MT5BridgeBrokerAdapter:
    """HTTP client for ``mt5-bridge/`` — the self-hosted, subscription-free
    MT5 broker adapter (see mt5-bridge/README.md for the "why").

    Args:
        base_url:      the bridge service's private URL, e.g. "http://10.0.0.5:8001".
        secret:        shared bearer secret, must match the bridge's MT5_BRIDGE_SECRET.
        symbol_suffix: broker-specific suffix (e.g. ".m" for Exness / Justmarkets).
                       Applied when writing symbols to the bridge; stripped when
                       reading them back.
        client:        injected httpx.AsyncClient (tests pass a MockTransport-backed
                       one); a real client is built lazily otherwise.
    """

    def __init__(
        self,
        base_url: str,
        secret: str,
        symbol_suffix: str | None = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._symbol_suffix = symbol_suffix
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {secret}"},
            timeout=10.0,
        )

    def _broker_symbol(self, canonical: str) -> str:
        return normalize(canonical, self._symbol_suffix)

    def _canonical_symbol(self, broker_symbol: str) -> str:
        return denormalize(broker_symbol, self._symbol_suffix)

    async def get_open_positions(self) -> list[BrokerPosition]:
        resp = await self._client.get("/positions")
        resp.raise_for_status()
        return [
            BrokerPosition(
                position_id=row["position_id"],
                symbol=self._canonical_symbol(row["symbol"]),
                direction=row["direction"],
                volume=row["volume"],
            )
            for row in resp.json()
        ]

    async def get_working_orders(self) -> list[BrokerOrder]:
        resp = await self._client.get("/orders")
        resp.raise_for_status()
        return [
            BrokerOrder(
                order_id=row["order_id"],
                symbol=self._canonical_symbol(row["symbol"]),
                direction=row["direction"],
                volume=row["volume"],
            )
            for row in resp.json()
        ]

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

        resp = await self._client.post(
            "/orders",
            json={
                "client_id": client_id,
                "symbol": self._broker_symbol(symbol),
                "direction": direction,
                "volume": volume,
                "stop_loss": stop_loss,
                "take_profit": take_profit[0],  # bridge takes a single TP; use the first target
            },
        )
        resp.raise_for_status()
        row = resp.json()
        return BrokerPosition(
            position_id=row["position_id"],
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
        resp = await self._client.post(
            f"/positions/{position_id}/modify",
            json={"stop_loss": stop_loss, "take_profit": take_profit},
        )
        resp.raise_for_status()

    async def close_position(self, position_id: str) -> None:
        resp = await self._client.post(f"/positions/{position_id}/close")
        resp.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()
