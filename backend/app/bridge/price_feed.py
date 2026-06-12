"""MetaApi streaming price feed.

INTERNAL infrastructure: no public ingress (CLAUDE.md). Subscribes to MetaApi's
streaming connection and converts ``MetatraderSymbolPrice`` updates into
``agent_loop.Tick`` objects, queued for the live runner's tick-routing task.

Mirrors ``bridge/broker.py``'s lazy-connection style: the streaming connection
is created on the first ``connect()`` call. Symbols are normalised through
``symbol_normalizer`` the same way the broker adapter does.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from app.bridge.symbol_normalizer import denormalize, normalize
from app.engine.agent_loop import Tick

logger = logging.getLogger(__name__)

try:
    from metaapi_cloud_sdk import SynchronizationListener  # type: ignore[import]
except ImportError:  # SDK not installed (local dev / CI) — fall back to a plain base.
    class SynchronizationListener:  # type: ignore[no-redef]
        pass


class _PriceListener(SynchronizationListener):
    """Pushes a Tick onto the feed's queue for every symbol price update."""

    def __init__(self, queue: "asyncio.Queue[Tick]", symbol_suffix: str | None = None) -> None:
        super().__init__()
        self._queue = queue
        self._symbol_suffix = symbol_suffix

    async def on_symbol_price_updated(self, instance_index: str, price: dict) -> None:
        tick = Tick(
            symbol=denormalize(price["symbol"], self._symbol_suffix),
            bid=float(price["bid"]),
            ask=float(price["ask"]),
            timestamp=datetime.now(timezone.utc),
        )
        await self._queue.put(tick)


class MetaApiPriceFeed:
    """Streams live price ticks for the symbols the live runner subscribes to.

    One instance per account; the streaming connection is created lazily on
    the first ``connect()`` call and reused for the process lifetime.
    """

    def __init__(self, token: str, account_id: str, symbol_suffix: str | None = None) -> None:
        self._token = token
        self._account_id = account_id
        self._symbol_suffix = symbol_suffix
        self._conn = None  # lazy — created in connect()
        self._queue: "asyncio.Queue[Tick]" = asyncio.Queue()

    async def connect(self) -> None:
        if self._conn is not None:
            return
        try:
            from metaapi_cloud_sdk import MetaApi  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "metaapi-cloud-sdk is not installed. "
                "Add it to requirements.txt and rebuild the Docker image."
            ) from exc

        api = MetaApi(self._token)
        account = await api.metatrader_account_api.get_account(self._account_id)
        conn = await account.get_streaming_connection()
        conn.add_synchronization_listener(_PriceListener(self._queue, self._symbol_suffix))
        await conn.connect()
        await conn.wait_synchronized()
        self._conn = conn
        logger.info("MetaApi streaming connection established for account %s", self._account_id)

    async def subscribe(self, symbols: set[str]) -> None:
        if self._conn is None:
            raise RuntimeError("connect() must be called before subscribe()")
        for symbol in symbols:
            await self._conn.subscribe_to_market_data(normalize(symbol, self._symbol_suffix))

    async def ticks(self) -> AsyncIterator[Tick]:
        while True:
            yield await self._queue.get()

    async def aclose(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
