"""Tests for the agent loop state machine, pure helpers, and interface conformance.

All async methods are exercised via synchronous wrappers (asyncio.run), matching
the project's existing test pattern (no pytest-asyncio installed).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.agent_loop import (
    ActiveProposal,
    AgentLoop,
    ConditionEvaluator,
    DecisionLogger,
    LoopState,
    Tick,
    TelegramNotifier,
    _pip_size,
    circuit_breaker_tripped,
    compute_sl_price,
    compute_tp_prices,
)
from app.contract.schemas import (
    CircuitBreaker,
    ConditionGroup,
    ExecutionSpec,
    ExitSpec,
    IndicatorCondition,
    Instrument,
    PerTradeRisk,
    RiskGuards,
    RiskSpec,
    Setup,
    StopLoss,
    StrategyMetadata,
    StrategySpec,
    TakeProfitLeg,
    Timeframes,
)

run = asyncio.run

# --------------------------------------------------------------------------- #
# Minimal strategy spec fixture                                                #
# --------------------------------------------------------------------------- #

_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _make_spec(direction: str = "long", validity: int = 300) -> StrategySpec:
    return StrategySpec(
        id="strat-1",
        name="Test Strategy",
        instrument=Instrument(symbol="EURUSD", asset_class="forex"),
        timeframes=Timeframes(entry="H1"),
        setups=[
            Setup(
                name="Test Setup",
                direction=direction,
                entry=ConditionGroup(
                    operator="all",
                    children=[
                        IndicatorCondition(
                            kind="indicator",
                            indicator="RSI",
                            params={"period": 14},
                            comparator="lt",
                            value=30.0,
                        )
                    ],
                ),
                exit=ExitSpec(
                    stop_loss=StopLoss(model="fixed_pips", value=50),
                    take_profit=[TakeProfitLeg(model="rr", value=2.0, close_percent=100)],
                ),
                per_trade_risk=PerTradeRisk(model="fixed_percent", value=1.0),
            )
        ],
        risk=RiskSpec(guards=RiskGuards()),
        execution=ExecutionSpec(
            mode="semi_auto",
            validity_window_seconds=validity,
            circuit_breaker=CircuitBreaker(slip_invalidate_fraction=0.5),
        ),
        version=1,
        metadata=StrategyMetadata(
            created_at="2026-06-09T00:00:00Z",
            updated_at="2026-06-09T00:00:00Z",
            author_user_id="user-1",
        ),
    )


def _make_tick(
    bid: float = 1.08000,
    ask: float = 1.08002,
    ts: datetime | None = None,
) -> Tick:
    return Tick(
        symbol="EURUSD",
        bid=bid,
        ask=ask,
        timestamp=ts or _T0,
    )


# --------------------------------------------------------------------------- #
# Loop fixture                                                                 #
# --------------------------------------------------------------------------- #


def _make_loop(
    direction: str = "long",
    match: bool = False,
    validity: int = 300,
    cooldown: int = 60,
    now_fn=None,
):
    spec = _make_spec(direction=direction, validity=validity)

    broker = AsyncMock()
    broker.place_order = AsyncMock(
        return_value=MagicMock(position_id="pos-1")
    )

    store = AsyncMock()
    store.put_pending_proposal = AsyncMock()
    store.get_pending_proposal = AsyncMock(return_value=None)
    store.delete_pending_proposal = AsyncMock()
    store.mark_idempotency_key = AsyncMock()
    store.is_idempotency_key_used = AsyncMock(return_value=False)
    store.set_open_position_flag = AsyncMock()
    store.clear_open_position_flag = AsyncMock()
    store.has_open_position = AsyncMock(return_value=False)

    telegram = AsyncMock()
    telegram.send_proposal = AsyncMock()
    telegram.send_invalidation = AsyncMock()

    logger = AsyncMock()
    logger.log_proposal = AsyncMock()
    logger.log_decision = AsyncMock()

    class _Eval:
        def evaluate(self, tick, setup):
            return match

    loop = AgentLoop(
        spec=spec,
        broker=broker,
        state_store=store,
        telegram=telegram,
        logger=logger,
        evaluator=_Eval(),
        cooldown_seconds=cooldown,
        now_fn=now_fn or (lambda: _T0),
    )
    return loop, broker, store, telegram, logger


# --------------------------------------------------------------------------- #
# Pure helpers — _pip_size                                                     #
# --------------------------------------------------------------------------- #


def test_pip_size_forex():
    assert _pip_size("EURUSD") == 0.0001


def test_pip_size_jpy():
    assert _pip_size("USDJPY") == 0.01


def test_pip_size_xauusd():
    assert _pip_size("XAUUSD") == 0.0001


# --------------------------------------------------------------------------- #
# Pure helpers — compute_sl_price                                              #
# --------------------------------------------------------------------------- #


def test_compute_sl_price_long():
    # 50 pip SL on EURUSD from 1.0800 => 1.0800 - 0.0050 = 1.0750
    sl = compute_sl_price(1.0800, "long", 50, "EURUSD")
    assert abs(sl - 1.0750) < 1e-9


def test_compute_sl_price_short():
    sl = compute_sl_price(1.0800, "short", 50, "EURUSD")
    assert abs(sl - 1.0850) < 1e-9


def test_compute_sl_price_jpy():
    # USDJPY: 50 pips at 0.01 = 0.50
    sl = compute_sl_price(150.00, "long", 50, "USDJPY")
    assert abs(sl - 149.50) < 1e-9


# --------------------------------------------------------------------------- #
# Pure helpers — compute_tp_prices                                             #
# --------------------------------------------------------------------------- #


def test_compute_tp_rr_long():
    entry, sl = 1.0800, 1.0750  # 50 pip stop
    legs = [TakeProfitLeg(model="rr", value=2.0, close_percent=100)]
    tps = compute_tp_prices(entry, "long", sl, legs, "EURUSD")
    assert len(tps) == 1
    # 2:1 RR => 100 pip TP => 1.0900
    assert abs(tps[0] - 1.0900) < 1e-9


def test_compute_tp_rr_short():
    entry, sl = 1.0800, 1.0850
    legs = [TakeProfitLeg(model="rr", value=2.0, close_percent=100)]
    tps = compute_tp_prices(entry, "short", sl, legs, "EURUSD")
    assert abs(tps[0] - 1.0700) < 1e-9


def test_compute_tp_fixed_pips():
    entry, sl = 1.0800, 1.0750
    legs = [TakeProfitLeg(model="fixed_pips", value=100, close_percent=100)]
    tps = compute_tp_prices(entry, "long", sl, legs, "EURUSD")
    assert abs(tps[0] - 1.0900) < 1e-9


def test_compute_tp_multiple_legs():
    entry, sl = 1.0800, 1.0750
    legs = [
        TakeProfitLeg(model="rr", value=1.0, close_percent=50),
        TakeProfitLeg(model="rr", value=2.0, close_percent=50),
    ]
    tps = compute_tp_prices(entry, "long", sl, legs, "EURUSD")
    assert len(tps) == 2
    assert abs(tps[0] - 1.0850) < 1e-9
    assert abs(tps[1] - 1.0900) < 1e-9


def test_compute_tp_empty_legs():
    assert compute_tp_prices(1.08, "long", 1.075, [], "EURUSD") == []


# --------------------------------------------------------------------------- #
# Pure helpers — circuit_breaker_tripped                                       #
# --------------------------------------------------------------------------- #


def _make_proposal(
    direction: str = "long",
    entry: float = 1.0800,
    sl: float | None = None,
) -> ActiveProposal:
    if sl is None:
        sl = 1.0750 if direction == "long" else 1.0850
    sl_dist = abs(entry - sl)
    return ActiveProposal(
        proposal_id="p1",
        strategy_id="s1",
        symbol="EURUSD",
        direction=direction,
        entry_price=entry,
        stop_loss_price=sl,
        take_profit_prices=[],
        confidence_score=0.7,
        rationale="test",
        proposed_at=_T0,
        expires_at=_T0 + timedelta(minutes=5),
        sl_distance=sl_dist,
    )


def test_circuit_breaker_not_tripped_long():
    prop = _make_proposal("long", entry=1.0800, sl=1.0750)
    # 50% of 50 pips = 25 pips; price is 20 pips against entry => no trip
    tick = _make_tick(bid=1.0779, ask=1.0780)  # 20 pips below entry
    assert not circuit_breaker_tripped(tick, prop, 0.5)


def test_circuit_breaker_tripped_long():
    prop = _make_proposal("long", entry=1.0800, sl=1.0750)
    # threshold = 0.5 * 0.0050 = 0.0025 => 1.0775
    # price at ask = 1.0774 < 1.0775 => tripped
    tick = _make_tick(bid=1.0773, ask=1.0774)
    assert circuit_breaker_tripped(tick, prop, 0.5)


def test_circuit_breaker_not_tripped_short():
    prop = _make_proposal("short", entry=1.0800, sl=1.0850)
    tick = _make_tick(bid=1.0819, ask=1.0820)  # 20 pips above entry
    assert not circuit_breaker_tripped(tick, prop, 0.5)


def test_circuit_breaker_tripped_short():
    prop = _make_proposal("short", entry=1.0800, sl=1.0850)
    # threshold = 0.0025 => 1.0825; bid = 1.0826 > 1.0825 => tripped
    tick = _make_tick(bid=1.0826, ask=1.0827)
    assert circuit_breaker_tripped(tick, prop, 0.5)


def test_circuit_breaker_clearly_inside_threshold_not_tripped():
    # 1 pip inside the threshold — should not trip.
    prop = _make_proposal("long", entry=1.0800, sl=1.0750)
    # threshold at 1.0775 (50% of 50 pip stop); ask = 1.0776 is 1 pip above it
    tick = _make_tick(bid=1.0775, ask=1.0776)
    assert not circuit_breaker_tripped(tick, prop, 0.5)


# --------------------------------------------------------------------------- #
# State machine — FLAT                                                         #
# --------------------------------------------------------------------------- #


def test_initial_state_is_flat():
    loop, *_ = _make_loop()
    assert loop.state == LoopState.FLAT


def test_tick_with_no_match_stays_flat():
    loop, _, _, telegram, _ = _make_loop(match=False)
    run(loop.on_tick(_make_tick()))
    assert loop.state == LoopState.FLAT
    telegram.send_proposal.assert_not_called()


def test_tick_with_match_enters_seeking():
    loop, _, store, telegram, logger = _make_loop(match=True)
    run(loop.on_tick(_make_tick()))

    assert loop.state == LoopState.SEEKING
    telegram.send_proposal.assert_called_once()
    logger.log_proposal.assert_called_once()
    store.put_pending_proposal.assert_called_once()
    store.set_open_position_flag.assert_called_once_with("strat-1", "EURUSD")


def test_seeking_proposal_has_correct_direction_and_symbol():
    loop, _, _, telegram, _ = _make_loop(match=True)
    run(loop.on_tick(_make_tick(ask=1.0800)))

    proposal: ActiveProposal = telegram.send_proposal.call_args[0][0]
    assert proposal.symbol == "EURUSD"
    assert proposal.direction == "long"
    assert proposal.entry_price == 1.0800  # long fills at ask


def test_seeking_proposal_short_fills_at_bid():
    loop, _, _, telegram, _ = _make_loop(match=True, direction="short")
    run(loop.on_tick(_make_tick(bid=1.0799, ask=1.0800)))

    proposal: ActiveProposal = telegram.send_proposal.call_args[0][0]
    assert proposal.direction == "short"
    assert proposal.entry_price == 1.0799  # short fills at bid


def test_seeking_proposal_sl_tp_computed():
    loop, _, _, telegram, _ = _make_loop(match=True)
    run(loop.on_tick(_make_tick(ask=1.0800)))

    proposal: ActiveProposal = telegram.send_proposal.call_args[0][0]
    # 50 pip SL on EURUSD: 1.0800 - 0.0050 = 1.0750
    assert abs(proposal.stop_loss_price - 1.0750) < 1e-9
    # 2:1 RR TP: 1.0800 + 0.0100 = 1.0900
    assert len(proposal.take_profit_prices) == 1
    assert abs(proposal.take_profit_prices[0] - 1.0900) < 1e-9


def test_seeking_proposal_validity_window():
    loop, _, _, telegram, _ = _make_loop(match=True, validity=300)
    run(loop.on_tick(_make_tick()))

    proposal: ActiveProposal = telegram.send_proposal.call_args[0][0]
    delta = (proposal.expires_at - proposal.proposed_at).total_seconds()
    assert delta == 300


# --------------------------------------------------------------------------- #
# State machine — SEEKING: window expiry                                       #
# --------------------------------------------------------------------------- #


def test_seeking_tick_within_window_stays_seeking():
    clock = [_T0]
    loop, _, _, telegram, logger = _make_loop(
        match=True, now_fn=lambda: clock[0]
    )
    run(loop.on_tick(_make_tick()))  # enters SEEKING at T0
    assert loop.state == LoopState.SEEKING

    # tick 1 second later — still within 300s window
    clock[0] = _T0 + timedelta(seconds=1)
    run(loop.on_tick(_make_tick()))
    assert loop.state == LoopState.SEEKING
    telegram.send_invalidation.assert_not_called()


def test_seeking_tick_after_expiry_invalidates():
    clock = [_T0]
    loop, _, store, telegram, logger = _make_loop(
        match=True, validity=300, now_fn=lambda: clock[0]
    )
    run(loop.on_tick(_make_tick()))  # enters SEEKING

    # advance past expiry
    clock[0] = _T0 + timedelta(seconds=301)
    run(loop.on_tick(_make_tick()))

    assert loop.state == LoopState.FLAT
    telegram.send_invalidation.assert_called_once()
    logger.log_decision.assert_called_with(
        loop._proposal or logger.log_decision.call_args[0][0],
        "invalidated",
    )
    store.delete_pending_proposal.assert_called()
    store.clear_open_position_flag.assert_called()


# --------------------------------------------------------------------------- #
# State machine — SEEKING: circuit breaker                                     #
# --------------------------------------------------------------------------- #


def test_seeking_circuit_breaker_tripped_invalidates():
    loop, _, store, telegram, logger = _make_loop(match=True)
    run(loop.on_tick(_make_tick(ask=1.0800)))  # entry = 1.0800, SL at 1.0750

    # SL dist = 0.0050, threshold = 0.0025 => 1.0775
    # Send price below threshold
    run(loop.on_tick(_make_tick(bid=1.0773, ask=1.0774)))

    assert loop.state == LoopState.FLAT
    telegram.send_invalidation.assert_called_once()
    store.delete_pending_proposal.assert_called()


def test_seeking_price_within_threshold_no_invalidation():
    loop, _, _, telegram, _ = _make_loop(match=True)
    run(loop.on_tick(_make_tick(ask=1.0800)))

    # 20 pips below entry = 1.0780 (ask); threshold is 1.0775 — no trip
    run(loop.on_tick(_make_tick(bid=1.0779, ask=1.0780)))
    assert loop.state == LoopState.SEEKING
    telegram.send_invalidation.assert_not_called()


# --------------------------------------------------------------------------- #
# State machine — SEEKING: approval                                            #
# --------------------------------------------------------------------------- #


def test_approval_within_window_places_order():
    loop, broker, store, _, logger = _make_loop(match=True)
    run(loop.on_tick(_make_tick()))

    proposal_id = loop._proposal.proposal_id
    run(loop.on_approval(proposal_id, used_keys=set()))

    assert loop.state == LoopState.IN_POSITION
    broker.place_order.assert_called_once()
    store.mark_idempotency_key.assert_called_once_with(proposal_id)
    store.delete_pending_proposal.assert_called_with(proposal_id)
    logger.log_decision.assert_called_with(
        loop._proposal or logger.log_decision.call_args[0][0],
        "approve",
    )


def test_approval_carries_sl_tp_to_broker():
    loop, broker, *_ = _make_loop(match=True)
    run(loop.on_tick(_make_tick(ask=1.0800)))
    proposal_id = loop._proposal.proposal_id
    run(loop.on_approval(proposal_id, used_keys=set()))

    call = broker.place_order.call_args
    assert abs(call.kwargs["stop_loss"] - 1.0750) < 1e-9
    assert len(call.kwargs["take_profit"]) == 1
    assert abs(call.kwargs["take_profit"][0] - 1.0900) < 1e-9
    assert call.kwargs["client_id"] == proposal_id


def test_approval_after_expiry_invalidates_not_places():
    clock = [_T0]
    loop, broker, _, telegram, _ = _make_loop(
        match=True, validity=300, now_fn=lambda: clock[0]
    )
    run(loop.on_tick(_make_tick()))
    proposal_id = loop._proposal.proposal_id

    clock[0] = _T0 + timedelta(seconds=301)
    run(loop.on_approval(proposal_id, used_keys=set()))

    assert loop.state == LoopState.FLAT
    broker.place_order.assert_not_called()
    telegram.send_invalidation.assert_called_once()


def test_approval_idempotency_guard_suppresses_duplicate():
    loop, broker, *_ = _make_loop(match=True)
    run(loop.on_tick(_make_tick()))
    proposal_id = loop._proposal.proposal_id

    # Key already used — simulate double callback
    run(loop.on_approval(proposal_id, used_keys={proposal_id}))
    broker.place_order.assert_not_called()


def test_approval_wrong_proposal_id_ignored():
    loop, broker, *_ = _make_loop(match=True)
    run(loop.on_tick(_make_tick()))
    run(loop.on_approval("other-proposal", used_keys=set()))
    broker.place_order.assert_not_called()
    assert loop.state == LoopState.SEEKING


def test_approval_when_not_seeking_ignored():
    loop, broker, *_ = _make_loop(match=False)
    run(loop.on_approval("any-id", used_keys=set()))
    broker.place_order.assert_not_called()


# --------------------------------------------------------------------------- #
# State machine — SEEKING: rejection                                           #
# --------------------------------------------------------------------------- #


def test_rejection_clears_to_flat():
    loop, broker, store, _, logger = _make_loop(match=True)
    run(loop.on_tick(_make_tick()))
    proposal_id = loop._proposal.proposal_id

    run(loop.on_rejection(proposal_id, reason="bad_timing"))

    assert loop.state == LoopState.FLAT
    broker.place_order.assert_not_called()
    store.delete_pending_proposal.assert_called_with(proposal_id)
    store.clear_open_position_flag.assert_called()
    logger.log_decision.assert_called_with(
        logger.log_decision.call_args[0][0], "reject", reject_reason="bad_timing"
    )


def test_rejection_wrong_proposal_id_ignored():
    loop, *_ = _make_loop(match=True)
    run(loop.on_tick(_make_tick()))
    run(loop.on_rejection("wrong-id"))
    assert loop.state == LoopState.SEEKING


def test_rejection_when_not_seeking_ignored():
    loop, broker, *_ = _make_loop(match=False)
    run(loop.on_rejection("any-id"))
    assert loop.state == LoopState.FLAT


# --------------------------------------------------------------------------- #
# State machine — IN_POSITION -> COOLDOWN -> FLAT                             #
# --------------------------------------------------------------------------- #


def test_in_position_tick_does_not_trigger_new_proposal():
    loop, _, _, telegram, _ = _make_loop(match=True)
    run(loop.on_tick(_make_tick()))
    run(loop.on_approval(loop._proposal.proposal_id, used_keys=set()))
    assert loop.state == LoopState.IN_POSITION

    telegram.send_proposal.reset_mock()
    run(loop.on_tick(_make_tick()))  # tick while in position
    assert loop.state == LoopState.IN_POSITION
    telegram.send_proposal.assert_not_called()


def test_position_closed_enters_cooldown():
    clock = [_T0]
    loop, *_ = _make_loop(match=True, cooldown=60, now_fn=lambda: clock[0])
    run(loop.on_tick(_make_tick()))
    run(loop.on_approval(loop._proposal.proposal_id, used_keys=set()))

    run(loop.on_position_closed("pos-1"))
    assert loop.state == LoopState.COOLDOWN


def test_position_closed_wrong_id_ignored():
    loop, *_ = _make_loop(match=True)
    run(loop.on_tick(_make_tick()))
    run(loop.on_approval(loop._proposal.proposal_id, used_keys=set()))

    run(loop.on_position_closed("wrong-pos"))
    assert loop.state == LoopState.IN_POSITION


def test_cooldown_expires_to_flat():
    clock = [_T0]
    loop, *_ = _make_loop(match=True, cooldown=60, now_fn=lambda: clock[0])
    run(loop.on_tick(_make_tick()))
    run(loop.on_approval(loop._proposal.proposal_id, used_keys=set()))
    run(loop.on_position_closed("pos-1"))
    assert loop.state == LoopState.COOLDOWN

    # still in cooldown 30 seconds later
    clock[0] = _T0 + timedelta(seconds=30)
    run(loop.on_tick(_make_tick()))
    assert loop.state == LoopState.COOLDOWN

    # past cooldown
    clock[0] = _T0 + timedelta(seconds=61)
    run(loop.on_tick(_make_tick()))
    assert loop.state == LoopState.FLAT


def test_full_happy_path_flat_to_flat():
    """Flat -> seeking -> in_position -> cooldown -> flat end-to-end."""
    clock = [_T0]
    loop, _, _, telegram, logger = _make_loop(
        match=True, cooldown=60, now_fn=lambda: clock[0]
    )

    run(loop.on_tick(_make_tick()))
    assert loop.state == LoopState.SEEKING

    proposal_id = loop._proposal.proposal_id
    run(loop.on_approval(proposal_id, used_keys=set()))
    assert loop.state == LoopState.IN_POSITION

    run(loop.on_position_closed("pos-1"))
    assert loop.state == LoopState.COOLDOWN

    clock[0] = _T0 + timedelta(seconds=61)
    run(loop.on_tick(_make_tick()))
    assert loop.state == LoopState.FLAT

    # Should be ready to seek again.
    run(loop.on_tick(_make_tick()))
    assert loop.state == LoopState.SEEKING


# --------------------------------------------------------------------------- #
# Protocol conformance                                                         #
# --------------------------------------------------------------------------- #


def test_agent_loop_accepts_protocol_conformant_notifier():
    class _FakeNotifier:
        async def send_proposal(self, proposal):
            pass

        async def send_invalidation(self, proposal_id, reason):
            pass

    assert isinstance(_FakeNotifier(), TelegramNotifier)


def test_agent_loop_accepts_protocol_conformant_logger():
    class _FakeLogger:
        async def log_proposal(self, proposal):
            pass

        async def log_decision(self, proposal, decision, reject_reason=None):
            pass

    assert isinstance(_FakeLogger(), DecisionLogger)


def test_agent_loop_accepts_protocol_conformant_evaluator():
    class _FakeEval:
        def evaluate(self, tick, setup):
            return False

    assert isinstance(_FakeEval(), ConditionEvaluator)
