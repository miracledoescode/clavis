"""Domain types for live-engine state and crash recovery (slice 4 safety contract).

PURE data only — no I/O. These model the three layers of truth from CLAUDE.md's
"State and Recovery":
  - the BROKER (authoritative) — BrokerPosition / BrokerOrder
  - what Clavis EXPECTED (Postgres durable record + Redis hot state) — ExpectedState
  - the reconciliation output — ReconcileAction
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

Side = Literal["long", "short"]


@dataclass(frozen=True)
class BrokerPosition:
    """An open position as the broker (MetaApi) reports it — the source of truth."""

    position_id: str  # broker ticket / position id
    symbol: str
    direction: Side
    volume: float
    # The client order id we attached when sending (== the proposal's idempotency
    # key). None for positions opened outside Clavis (e.g. manually at the broker).
    client_id: Optional[str] = None


@dataclass(frozen=True)
class BrokerOrder:
    """A working (not yet filled) order at the broker."""

    order_id: str
    symbol: str
    direction: Side
    volume: float
    client_id: Optional[str] = None


@dataclass(frozen=True)
class ExpectedPosition:
    """A position Clavis believes is open (from Postgres + Redis hot state)."""

    proposal_id: str
    symbol: str
    direction: Side
    volume: float
    broker_position_id: Optional[str] = None


@dataclass(frozen=True)
class PendingProposal:
    """A proposal awaiting / within its validity window when the process went down."""

    proposal_id: str
    symbol: str
    expires_at: datetime


@dataclass
class ExpectedState:
    """Everything Clavis expected to be true at boot (durable + hot state)."""

    positions: list[ExpectedPosition] = field(default_factory=list)
    pending_proposals: list[PendingProposal] = field(default_factory=list)


ActionKind = Literal["adopt", "close_out", "invalidate", "noop"]


@dataclass(frozen=True)
class ReconcileAction:
    """One step the boot reconciliation says to take. Inert data; the caller acts."""

    kind: ActionKind
    target: Literal["position", "proposal"]
    reason: str
    proposal_id: Optional[str] = None
    broker_position_id: Optional[str] = None
    symbol: Optional[str] = None
