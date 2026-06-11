"""UpstashRedisStore: StateStore backed by an in-memory fake Upstash client.

Exercises all 11 StateStore methods against `FakeUpstashRedis`, a minimal
stand-in implementing the handful of `upstash_redis.asyncio.Redis` commands
`UpstashRedisStore` calls (`get`, `set`, `delete`, `sadd`, `srem`, `smembers`,
`exists`) — no network, no real Upstash account needed.
"""
from __future__ import annotations

import asyncio

import pytest

from app.engine.hot_state import (
    PENDING_PROPOSALS_SET,
    USED_IDEMPOTENCY_KEYS_SET,
    UpstashRedisStore,
    idempotency_marker_key,
    open_position_flag_key,
    proposal_key,
)


class FakeUpstashRedis:
    """In-memory stand-in for the subset of upstash_redis.asyncio.Redis used here."""

    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}

    async def get(self, key: str):
        return self._strings.get(key)

    async def set(self, key: str, value, ex=None, **_kwargs):
        self._strings[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self._strings.pop(key, None) is not None:
                removed += 1
        return removed

    async def sadd(self, key: str, *members: str) -> int:
        s = self._sets.setdefault(key, set())
        added = 0
        for m in members:
            if m not in s:
                s.add(m)
                added += 1
        return added

    async def srem(self, key: str, *members: str) -> int:
        s = self._sets.get(key, set())
        removed = 0
        for m in members:
            if m in s:
                s.discard(m)
                removed += 1
        return removed

    async def smembers(self, key: str):
        return set(self._sets.get(key, set()))

    async def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if k in self._strings)

    def expire_now(self, key: str) -> None:
        """Test helper: simulate TTL eviction without touching index sets."""
        self._strings.pop(key, None)


@pytest.fixture
def store():
    return UpstashRedisStore(client=FakeUpstashRedis())


# --------------------------------------------------------------------------- #
# pending proposals + validity windows                                        #
# --------------------------------------------------------------------------- #
def test_put_and_get_pending_proposal(store):
    async def run():
        await store.put_pending_proposal("p1", {"symbol": "EURUSD", "direction": "long"}, ttl_seconds=300)
        return await store.get_pending_proposal("p1")

    assert asyncio.run(run()) == {"symbol": "EURUSD", "direction": "long"}


def test_get_pending_proposal_missing_returns_none(store):
    assert asyncio.run(store.get_pending_proposal("nope")) is None


def test_list_pending_proposals_returns_all(store):
    async def run():
        await store.put_pending_proposal("p1", {"symbol": "EURUSD"}, ttl_seconds=300)
        await store.put_pending_proposal("p2", {"symbol": "GBPUSD"}, ttl_seconds=300)
        return await store.list_pending_proposals()

    proposals = asyncio.run(run())
    assert {p["symbol"] for p in proposals} == {"EURUSD", "GBPUSD"}


def test_list_pending_proposals_drops_ttl_expired_and_cleans_index(store):
    fake = store._client

    async def run():
        await store.put_pending_proposal("p1", {"symbol": "EURUSD"}, ttl_seconds=300)
        await store.put_pending_proposal("p2", {"symbol": "GBPUSD"}, ttl_seconds=1)
        # Simulate p2's TTL having expired in Redis already.
        fake.expire_now(proposal_key("p2"))
        proposals = await store.list_pending_proposals()
        remaining_ids = await fake.smembers(PENDING_PROPOSALS_SET)
        return proposals, remaining_ids

    proposals, remaining_ids = asyncio.run(run())
    assert [p["symbol"] for p in proposals] == ["EURUSD"]
    assert remaining_ids == {"p1"}  # expired p2 removed from the index


def test_delete_pending_proposal_removes_payload_and_index(store):
    fake = store._client

    async def run():
        await store.put_pending_proposal("p1", {"symbol": "EURUSD"}, ttl_seconds=300)
        await store.delete_pending_proposal("p1")
        return await store.get_pending_proposal("p1"), await fake.smembers(PENDING_PROPOSALS_SET)

    payload, remaining_ids = asyncio.run(run())
    assert payload is None
    assert remaining_ids == set()


# --------------------------------------------------------------------------- #
# idempotency markers                                                          #
# --------------------------------------------------------------------------- #
def test_idempotency_key_unused_until_marked(store):
    async def run():
        before = await store.is_idempotency_key_used("p1")
        await store.mark_idempotency_key("p1")
        after = await store.is_idempotency_key_used("p1")
        return before, after

    before, after = asyncio.run(run())
    assert before is False
    assert after is True


def test_used_idempotency_keys_returns_all_marked(store):
    async def run():
        await store.mark_idempotency_key("p1")
        await store.mark_idempotency_key("p2")
        return await store.used_idempotency_keys()

    assert asyncio.run(run()) == {"p1", "p2"}


def test_idempotency_marker_persists_independent_of_used_set(store):
    fake = store._client

    async def run():
        await store.mark_idempotency_key("p1")
        # Even if the index set were lost, the marker key itself still answers
        # is_idempotency_key_used directly.
        fake._sets[USED_IDEMPOTENCY_KEYS_SET] = set()
        return await store.is_idempotency_key_used("p1")

    assert asyncio.run(run()) is True
    assert idempotency_marker_key("p1") in store._client._strings


# --------------------------------------------------------------------------- #
# open-position flags                                                          #
# --------------------------------------------------------------------------- #
def test_open_position_flag_lifecycle(store):
    async def run():
        before = await store.has_open_position("strat1", "EURUSD")
        await store.set_open_position_flag("strat1", "EURUSD")
        during = await store.has_open_position("strat1", "EURUSD")
        await store.clear_open_position_flag("strat1", "EURUSD")
        after = await store.has_open_position("strat1", "EURUSD")
        return before, during, after

    before, during, after = asyncio.run(run())
    assert before is False
    assert during is True
    assert after is False


def test_open_position_flags_are_per_strategy_and_symbol(store):
    async def run():
        await store.set_open_position_flag("strat1", "EURUSD")
        return (
            await store.has_open_position("strat1", "EURUSD"),
            await store.has_open_position("strat1", "GBPUSD"),
            await store.has_open_position("strat2", "EURUSD"),
        )

    same, other_symbol, other_strategy = asyncio.run(run())
    assert same is True
    assert other_symbol is False
    assert other_strategy is False


def test_key_schema_is_namespaced(store):
    assert proposal_key("p1") == "clavis:proposal:p1"
    assert idempotency_marker_key("p1") == "clavis:idem:p1"
    assert open_position_flag_key("s1", "EURUSD") == "clavis:open:s1:EURUSD"
