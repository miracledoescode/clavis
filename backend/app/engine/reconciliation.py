"""Pure boot-time reconciliation: diff real broker state against expected state.

On every boot the engine MUST reconcile BEFORE the loop resumes (CLAUDE.md
"State and Recovery"). This is the pure core: given what the broker actually
shows and what Clavis expected, return the actions to take. No I/O and no clock —
the caller passes `now` — so it is fully unit-testable.

Actions:
  adopt      a broker position Clavis does not recognise -> bring it under
             management WITHOUT opening anything new (never duplicate)
  close_out  an expected position the broker no longer shows -> it closed (SL/TP)
             while we were down; record the outcome
  invalidate a pending proposal whose validity window expired during downtime
  noop       already-managed positions, and proposals that are still valid or
             already executed -> nothing to do
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from app.engine.live_state import BrokerPosition, ExpectedPosition, ExpectedState, ReconcileAction


def _matches(bp: BrokerPosition, ep: ExpectedPosition) -> bool:
    """A broker position is the SAME as an expected one if the client key matches
    (preferred) or the broker ticket matches a known position id."""
    if bp.client_id is not None and bp.client_id == ep.proposal_id:
        return True
    if ep.broker_position_id is not None and bp.position_id == ep.broker_position_id:
        return True
    return False


def reconcile(
    broker_positions: Iterable[BrokerPosition],
    expected_state: ExpectedState,
    now: datetime,
) -> list[ReconcileAction]:
    broker_positions = list(broker_positions)
    actions: list[ReconcileAction] = []
    matched_expected: set[str] = set()

    # 1. Walk real broker positions: noop the already-managed, adopt the unknown.
    for bp in broker_positions:
        match: Optional[ExpectedPosition] = next(
            (ep for ep in expected_state.positions if _matches(bp, ep)), None
        )
        if match is not None:
            matched_expected.add(match.proposal_id)
            actions.append(
                ReconcileAction(
                    kind="noop",
                    target="position",
                    reason="broker position already managed",
                    proposal_id=match.proposal_id,
                    broker_position_id=bp.position_id,
                    symbol=bp.symbol,
                )
            )
        else:
            actions.append(
                ReconcileAction(
                    kind="adopt",
                    target="position",
                    reason="unknown broker position; adopt under management without duplicating",
                    proposal_id=bp.client_id,
                    broker_position_id=bp.position_id,
                    symbol=bp.symbol,
                )
            )

    # 2. Expected positions the broker no longer shows -> closed while we were down.
    for ep in expected_state.positions:
        if ep.proposal_id not in matched_expected:
            actions.append(
                ReconcileAction(
                    kind="close_out",
                    target="position",
                    reason="broker no longer shows this position; record the close-out outcome",
                    proposal_id=ep.proposal_id,
                    broker_position_id=ep.broker_position_id,
                    symbol=ep.symbol,
                )
            )

    # 3. Pending proposals. Already executed -> noop (never resend); expired ->
    #    invalidate; otherwise still valid -> noop (resume monitoring).
    executed_client_ids = {bp.client_id for bp in broker_positions if bp.client_id is not None}
    for prop in expected_state.pending_proposals:
        if prop.proposal_id in executed_client_ids:
            actions.append(
                ReconcileAction(
                    kind="noop",
                    target="proposal",
                    reason="proposal already executed at broker (position adopted); do not resend",
                    proposal_id=prop.proposal_id,
                    symbol=prop.symbol,
                )
            )
        elif prop.expires_at <= now:
            actions.append(
                ReconcileAction(
                    kind="invalidate",
                    target="proposal",
                    reason="validity window expired during downtime",
                    proposal_id=prop.proposal_id,
                    symbol=prop.symbol,
                )
            )
        else:
            actions.append(
                ReconcileAction(
                    kind="noop",
                    target="proposal",
                    reason="proposal still within its validity window; resume monitoring",
                    proposal_id=prop.proposal_id,
                    symbol=prop.symbol,
                )
            )

    return actions
