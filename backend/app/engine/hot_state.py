"""Redis hot-state KEY SCHEMA + the StateStore interface and Upstash impl.

Upstash Redis holds HOT state ONLY (CLAUDE.md "State and Recovery") — a cache and
coordination layer, never the source of truth:
  - pending proposals + their validity windows (stored with TTL == window)
  - idempotency markers (client keys that already produced a broker order)
  - open-position flags (prevent a duplicate entry while one is already open)

This module documents the key schema as constants, defines the StateStore
Protocol, and implements it against Upstash's HTTP-based `upstash-redis` client
(`UpstashRedisStore`) — chosen over `redis-py` because Upstash's REST API needs
no persistent TCP connection, which fits a serverless/Railway deployment.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Optional, Protocol, runtime_checkable

from upstash_redis.asyncio import Redis

from app import config

# --------------------------------------------------------------------------- #
# Key schema (documented constants — the single place these strings live)     #
# --------------------------------------------------------------------------- #
NAMESPACE = "clavis"


def proposal_key(proposal_id: str) -> str:
    """Pending proposal payload + validity window. Store with TTL ==
    validity_window_seconds so an expired window disappears on its own."""
    return f"{NAMESPACE}:proposal:{proposal_id}"


# Index set of currently-pending proposal ids (so boot reconciliation can scan).
PENDING_PROPOSALS_SET = f"{NAMESPACE}:proposals:pending"


def idempotency_marker_key(client_key: str) -> str:
    """Marker SET when a client key produces a broker order; checked on restart so
    we never resend. Persistent (or long retention), never TTL'd to under the
    longest plausible downtime."""
    return f"{NAMESPACE}:idem:{client_key}"


# Set index of used idempotency keys (feeds idempotency.should_send on boot).
USED_IDEMPOTENCY_KEYS_SET = f"{NAMESPACE}:idem:used"


def open_position_flag_key(strategy_id: str, symbol: str) -> str:
    """Per-(strategy, symbol) flag preventing a duplicate entry while open."""
    return f"{NAMESPACE}:open:{strategy_id}:{symbol}"


# --------------------------------------------------------------------------- #
# StateStore interface (Upstash Redis in slice 4)                             #
# --------------------------------------------------------------------------- #
@runtime_checkable
class StateStore(Protocol):
    """Hot-state store. Slice 4 backs this with Upstash Redis."""

    # Pending proposals + validity windows.
    async def put_pending_proposal(
        self, proposal_id: str, payload: Mapping[str, Any], ttl_seconds: int
    ) -> None: ...
    async def get_pending_proposal(self, proposal_id: str) -> Optional[dict]: ...
    async def list_pending_proposals(self) -> list[dict]: ...
    async def delete_pending_proposal(self, proposal_id: str) -> None: ...

    # Idempotency markers.
    async def mark_idempotency_key(self, client_key: str) -> None: ...
    async def is_idempotency_key_used(self, client_key: str) -> bool: ...
    async def used_idempotency_keys(self) -> set[str]: ...

    # Open-position flags.
    async def set_open_position_flag(self, strategy_id: str, symbol: str) -> None: ...
    async def clear_open_position_flag(self, strategy_id: str, symbol: str) -> None: ...
    async def has_open_position(self, strategy_id: str, symbol: str) -> bool: ...


class UpstashRedisStore:
    """StateStore backed by Upstash Redis (REST, async).

    Accepts an injected client satisfying the small subset of
    `upstash_redis.asyncio.Redis` used here (`get`, `set`, `delete`, `sadd`,
    `srem`, `smembers`, `exists`) — tests pass an in-memory fake; production
    builds the real client from `UPSTASH_REDIS_REST_URL`/`_TOKEN`.
    """

    def __init__(self, client: Optional[Any] = None) -> None:
        self._client = client or Redis(
            url=config.UPSTASH_REDIS_REST_URL,
            token=config.UPSTASH_REDIS_REST_TOKEN,
        )

    # -- pending proposals + validity windows -------------------------------- #
    async def put_pending_proposal(
        self, proposal_id: str, payload: Mapping[str, Any], ttl_seconds: int
    ) -> None:
        await self._client.set(proposal_key(proposal_id), json.dumps(dict(payload)), ex=ttl_seconds)
        await self._client.sadd(PENDING_PROPOSALS_SET, proposal_id)

    async def get_pending_proposal(self, proposal_id: str) -> Optional[dict]:
        raw = await self._client.get(proposal_key(proposal_id))
        return json.loads(raw) if raw is not None else None

    async def list_pending_proposals(self) -> list[dict]:
        proposal_ids = await self._client.smembers(PENDING_PROPOSALS_SET)
        proposals: list[dict] = []
        expired: list[str] = []
        for proposal_id in proposal_ids:
            raw = await self._client.get(proposal_key(proposal_id))
            if raw is None:
                # TTL already evicted the payload; drop it from the index too.
                expired.append(proposal_id)
                continue
            proposals.append(json.loads(raw))
        if expired:
            await self._client.srem(PENDING_PROPOSALS_SET, *expired)
        return proposals

    async def delete_pending_proposal(self, proposal_id: str) -> None:
        await self._client.delete(proposal_key(proposal_id))
        await self._client.srem(PENDING_PROPOSALS_SET, proposal_id)

    # -- idempotency markers --------------------------------------------------- #
    async def mark_idempotency_key(self, client_key: str) -> None:
        await self._client.set(idempotency_marker_key(client_key), "1")
        await self._client.sadd(USED_IDEMPOTENCY_KEYS_SET, client_key)

    async def is_idempotency_key_used(self, client_key: str) -> bool:
        return bool(await self._client.exists(idempotency_marker_key(client_key)))

    async def used_idempotency_keys(self) -> set[str]:
        return set(await self._client.smembers(USED_IDEMPOTENCY_KEYS_SET))

    # -- open-position flags ---------------------------------------------------- #
    async def set_open_position_flag(self, strategy_id: str, symbol: str) -> None:
        await self._client.set(open_position_flag_key(strategy_id, symbol), "1")

    async def clear_open_position_flag(self, strategy_id: str, symbol: str) -> None:
        await self._client.delete(open_position_flag_key(strategy_id, symbol))

    async def has_open_position(self, strategy_id: str, symbol: str) -> bool:
        return bool(await self._client.exists(open_position_flag_key(strategy_id, symbol)))
