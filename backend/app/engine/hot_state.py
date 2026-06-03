"""Redis hot-state KEY SCHEMA + the StateStore interface (slice 4 implements it).

Upstash Redis holds HOT state ONLY (CLAUDE.md "State and Recovery") — a cache and
coordination layer, never the source of truth:
  - pending proposals + their validity windows (stored with TTL == window)
  - idempotency markers (client keys that already produced a broker order)
  - open-position flags (prevent a duplicate entry while one is already open)

This module documents the key schema as constants and defines the StateStore
Protocol + a NotImplemented stub. NO Redis client is wired here.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Protocol, runtime_checkable

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


class NotImplementedStateStore:
    """Placeholder StateStore. Slice 4 replaces this with an Upstash-backed impl."""

    _MSG = "StateStore is wired in slice 4 (Upstash Redis); not implemented yet."

    async def put_pending_proposal(
        self, proposal_id: str, payload: Mapping[str, Any], ttl_seconds: int
    ) -> None:
        raise NotImplementedError(self._MSG)

    async def get_pending_proposal(self, proposal_id: str) -> Optional[dict]:
        raise NotImplementedError(self._MSG)

    async def list_pending_proposals(self) -> list[dict]:
        raise NotImplementedError(self._MSG)

    async def delete_pending_proposal(self, proposal_id: str) -> None:
        raise NotImplementedError(self._MSG)

    async def mark_idempotency_key(self, client_key: str) -> None:
        raise NotImplementedError(self._MSG)

    async def is_idempotency_key_used(self, client_key: str) -> bool:
        raise NotImplementedError(self._MSG)

    async def used_idempotency_keys(self) -> set[str]:
        raise NotImplementedError(self._MSG)

    async def set_open_position_flag(self, strategy_id: str, symbol: str) -> None:
        raise NotImplementedError(self._MSG)

    async def clear_open_position_flag(self, strategy_id: str, symbol: str) -> None:
        raise NotImplementedError(self._MSG)

    async def has_open_position(self, strategy_id: str, symbol: str) -> bool:
        raise NotImplementedError(self._MSG)
