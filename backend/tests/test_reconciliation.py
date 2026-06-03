"""Pure reconciliation diff — every branch covered with in-memory fakes.

adopt / close_out / invalidate / noop, plus duplicate-suppressed and the
already-executed (no-resend) case that prevents double execution on restart.
"""
from datetime import datetime, timedelta, timezone

from app.engine.live_state import (
    BrokerPosition,
    ExpectedPosition,
    ExpectedState,
    PendingProposal,
)
from app.engine.reconciliation import reconcile

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


def _kinds(actions):
    return [a.kind for a in actions]


def test_adopt_unknown_broker_position():
    broker = [BrokerPosition(position_id="T1", symbol="EURUSD", direction="long", volume=0.1)]
    actions = reconcile(broker, ExpectedState(), NOW)
    assert _kinds(actions) == ["adopt"]
    assert actions[0].broker_position_id == "T1"
    assert actions[0].target == "position"


def test_managed_position_is_noop_and_not_duplicated():
    # Broker echoes the client_id we set (== proposal_id) and we expect it.
    broker = [BrokerPosition(position_id="T1", symbol="EURUSD", direction="long", volume=0.1, client_id="p1")]
    expected = ExpectedState(
        positions=[ExpectedPosition(proposal_id="p1", symbol="EURUSD", direction="long", volume=0.1, broker_position_id="T1")]
    )
    actions = reconcile(broker, expected, NOW)
    assert _kinds(actions) == ["noop"]  # exactly one, NOT adopt -> duplicate suppressed
    assert actions[0].proposal_id == "p1"


def test_match_by_broker_ticket_when_client_id_missing():
    # Broker didn't echo a client_id, but the ticket matches our expected record.
    broker = [BrokerPosition(position_id="T1", symbol="EURUSD", direction="long", volume=0.1, client_id=None)]
    expected = ExpectedState(
        positions=[ExpectedPosition(proposal_id="p1", symbol="EURUSD", direction="long", volume=0.1, broker_position_id="T1")]
    )
    actions = reconcile(broker, expected, NOW)
    assert _kinds(actions) == ["noop"]


def test_close_out_position_broker_no_longer_shows():
    expected = ExpectedState(
        positions=[ExpectedPosition(proposal_id="p1", symbol="EURUSD", direction="long", volume=0.1, broker_position_id="T1")]
    )
    actions = reconcile([], expected, NOW)
    assert _kinds(actions) == ["close_out"]
    assert actions[0].proposal_id == "p1"


def test_invalidate_expired_proposal():
    expected = ExpectedState(
        pending_proposals=[PendingProposal(proposal_id="p9", symbol="EURUSD", expires_at=NOW - timedelta(seconds=1))]
    )
    actions = reconcile([], expected, NOW)
    assert _kinds(actions) == ["invalidate"]
    assert actions[0].target == "proposal"


def test_active_proposal_is_noop():
    expected = ExpectedState(
        pending_proposals=[PendingProposal(proposal_id="p9", symbol="EURUSD", expires_at=NOW + timedelta(minutes=4))]
    )
    actions = reconcile([], expected, NOW)
    assert _kinds(actions) == ["noop"]


def test_already_executed_proposal_is_not_resent():
    # The proposal produced a broker order (client_id == proposal_id) before the
    # crash; on restart it must NOT be re-sent, even though it is still "pending"
    # and its window has expired. This is the double-execution guard.
    broker = [BrokerPosition(position_id="T7", symbol="EURUSD", direction="short", volume=0.2, client_id="p7")]
    expected = ExpectedState(
        pending_proposals=[PendingProposal(proposal_id="p7", symbol="EURUSD", expires_at=NOW - timedelta(seconds=1))]
    )
    actions = reconcile(broker, expected, NOW)
    assert "adopt" in _kinds(actions)  # the orphaned position is adopted
    proposal_actions = [a for a in actions if a.target == "proposal"]
    assert len(proposal_actions) == 1
    assert proposal_actions[0].kind == "noop"
    assert "do not resend" in proposal_actions[0].reason


def test_mixed_scenario_hits_every_branch():
    broker = [
        BrokerPosition(position_id="T1", symbol="EURUSD", direction="long", volume=0.1, client_id="p1"),   # managed -> noop
        BrokerPosition(position_id="T2", symbol="GBPUSD", direction="short", volume=0.2, client_id=None),  # unknown -> adopt
    ]
    expected = ExpectedState(
        positions=[
            ExpectedPosition(proposal_id="p1", symbol="EURUSD", direction="long", volume=0.1, broker_position_id="T1"),
            ExpectedPosition(proposal_id="p3", symbol="XAUUSD", direction="long", volume=0.05, broker_position_id="T3"),  # gone -> close_out
        ],
        pending_proposals=[
            PendingProposal(proposal_id="p4", symbol="EURUSD", expires_at=NOW - timedelta(seconds=5)),  # expired -> invalidate
            PendingProposal(proposal_id="p5", symbol="EURUSD", expires_at=NOW + timedelta(minutes=3)),  # active -> noop
        ],
    )
    actions = reconcile(broker, expected, NOW)
    assert {"adopt", "close_out", "invalidate", "noop"} <= set(_kinds(actions))
    # One action per broker position + one per unmatched expected + one per proposal.
    assert len(actions) == 2 + 1 + 2
