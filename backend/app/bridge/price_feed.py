"""Self-hosted MT5 bridge price feed.

INTERNAL infrastructure: no public ingress (CLAUDE.md). MT5's local API has
no push/streaming mechanism (unlike MetaApi), so this polls the mt5-bridge
service's ``/tick`` endpoint per subscribed symbol at a fixed interval and
converts changed quotes into ``agent_loop.Tick`` objects, queued for the live
runner's tick-routing task. Symbols are normalised through
``symbol_normalizer`` the same way the broker adapter does.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import httpx

from app.bridge.symbol_normalizer import normalize
from app.engine.agent_loop import Tick

logger = logging.getLogger(__name__)


class MT5BridgePriceFeed:
    """Polls ``mt5-bridge/`` for ticks on every subscribed symbol.

    Args:
        base_url:             the bridge service's private URL.
        secret:                shared bearer secret, must match the bridge's MT5_BRIDGE_SECRET.
        symbol_suffix:         broker-specific suffix (e.g. ".m").
        poll_interval_seconds: how often each subscribed symbol is polled.
        client:                injected httpx.AsyncClient (tests pass a MockTransport-backed one).
    """

    def __init__(
        self,
        base_url: str,
        secret: str,
        symbol_suffix: str | None = None,
        poll_interval_seconds: float = 1.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._symbol_suffix = symbol_suffix
        self._poll_interval = poll_interval_seconds
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {secret}"},
            timeout=10.0,
        )
        self._queue: "asyncio.Queue[Tick]" = asyncio.Queue()
        self._symbols: set[str] = set()
        self._last_quote: dict[str, tuple[float, float]] = {}
        self._poll_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Nothing to establish up front — the HTTP client is lazy and polling
        only starts once a symbol is subscribed."""
        return None

    async def subscribe(self, symbols: set[str]) -> None:
        self._symbols |= symbols
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        while True:
            for symbol in list(self._symbols):
                await self._poll_one(symbol)
            await asyncio.sleep(self._poll_interval)

    async def _poll_one(self, symbol: str) -> None:
        broker_symbol = normalize(symbol, self._symbol_suffix)
        try:
            resp = await self._client.get("/tick", params={"symbol": broker_symbol})
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("mt5-bridge tick poll failed for %s", symbol, exc_info=True)
            return

        row = resp.json()
        bid, ask = float(row["bid"]), float(row["ask"])
        if self._last_quote.get(symbol) == (bid, ask):
            return  # unchanged since last poll — skip, don't flood the loop
        self._last_quote[symbol] = (bid, ask)
        await self._queue.put(
            Tick(symbol=symbol, bid=bid, ask=ask, timestamp=datetime.now(timezone.utc))
        )

    async def ticks(self) -> AsyncIterator[Tick]:
        while True:
            yield await self._queue.get()

    async def aclose(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        await self._client.aclose()
