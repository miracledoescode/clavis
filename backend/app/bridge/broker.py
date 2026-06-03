"""Broker adapter interface (the MetaApi bridge) — INTERNAL infrastructure.

No public ingress; the path is always Frontend -> FastAPI -> Bridge (CLAUDE.md).
This module defines the adapter Protocol that slice 4 implements against MetaApi,
plus a NotImplemented stub so the live loop can be built against a fixed surface.

SAFETY: SL and TP are ALWAYS set on the order at the broker — `place_order`
requires them, so an order cannot be sent without broker-managed stops.

NO MetaApi client is wired here.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from app.engine.live_state import BrokerOrder, BrokerPosition, Side


@runtime_checkable
class BrokerAdapter(Protocol):
    """What the engine needs from the broker. Implemented over MetaApi in slice 4."""

    async def get_open_positions(self) -> list[BrokerPosition]: ...
    async def get_working_orders(self) -> list[BrokerOrder]: ...
    async def get_position(self, position_id: str) -> Optional[BrokerPosition]: ...

    async def place_order(
        self,
        *,
        client_id: str,  # idempotency key (== proposal_id); set on the broker order
        symbol: str,
        direction: Side,
        volume: float,
        stop_loss: float,  # required — SL always at the broker
        take_profit: list[float],  # required — TP always at the broker
    ) -> BrokerPosition: ...

    async def close_position(self, position_id: str) -> None: ...


class NotImplementedBrokerAdapter:
    """Placeholder BrokerAdapter. Slice 4 implements this against MetaApi."""

    _MSG = "BrokerAdapter is wired in slice 4 (MetaApi); not implemented yet."

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

    async def close_position(self, position_id: str) -> None:
        raise NotImplementedError(self._MSG)
