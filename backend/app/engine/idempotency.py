"""Pure idempotency helpers for live order sends (slice 4 safety contract).

Every order send carries a client key derived from the proposal (the proposal_id),
PERSISTED before the send. On restart we never resend a key that already produced
a broker order — this is what prevents double execution. These helpers are pure;
the persistence of used keys lives behind StateStore (engine/hot_state.py).
See CLAUDE.md "State and Recovery".
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any


def _field(proposal: Any, name: str) -> Any:
    if isinstance(proposal, Mapping):
        return proposal.get(name)
    return getattr(proposal, name, None)


def idempotency_key(proposal: Any) -> str:
    """Deterministic client key for a proposal (the broker client order id).

    Prefers an explicit ``proposal_id`` / ``id`` — the client key the constitution
    mandates. Falls back to a stable hash of identifying fields so a key always
    exists. Accepts a mapping or any object with the attributes.
    """
    explicit = _field(proposal, "proposal_id") or _field(proposal, "id")
    if explicit:
        return str(explicit)
    basis = "|".join(
        str(_field(proposal, name) or "")
        for name in ("strategy_id", "symbol", "direction", "proposed_at", "entry_price")
    )
    if not basis.strip("|"):
        raise ValueError("cannot derive an idempotency key from an empty proposal")
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def should_send(proposal: Any, used_keys: set[str]) -> bool:
    """True only if this proposal's key has not already produced a broker order."""
    return idempotency_key(proposal) not in used_keys
