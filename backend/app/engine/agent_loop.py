"""Agent loop: match -> propose -> validate -> execute.

State machine: flat -> seeking -> in_position -> cooldown.
Event-based (price ticks and Telegram callbacks), not level polling.
Every state transition is deterministic; all I/O is injected so the pure
parts are fully unit-testable without network access.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from app.bridge.broker import BrokerAdapter
from app.contract.schemas import Setup, StrategySpec
from app.engine.hot_state import StateStore
from app.engine.idempotency import should_send
from app.engine.live_state import Side


# --------------------------------------------------------------------------- #
# Price tick                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Tick:
    """A single price event delivered to the loop."""

    symbol: str
    bid: float
    ask: float
    timestamp: datetime

    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    def fill_price(self, direction: Side) -> float:
        """Worst-case fill price: buy at ask, sell at bid."""
        return self.ask if direction == "long" else self.bid


# --------------------------------------------------------------------------- #
# State machine                                                                #
# --------------------------------------------------------------------------- #


class LoopState(Enum):
    FLAT = auto()         # no pending proposal, no open position
    SEEKING = auto()      # proposal sent to Telegram, validity window live
    IN_POSITION = auto()  # order placed, position open at the broker
    COOLDOWN = auto()     # position closed, waiting before next entry


# --------------------------------------------------------------------------- #
# Active proposal (held in memory while SEEKING)                              #
# --------------------------------------------------------------------------- #


@dataclass
class ActiveProposal:
    proposal_id: str
    strategy_id: str
    symbol: str
    direction: Side
    entry_price: float
    stop_loss_price: float
    take_profit_prices: list[float]
    confidence_score: float
    rationale: str
    proposed_at: datetime
    expires_at: datetime
    sl_distance: float  # abs distance entry -> SL; used by the circuit breaker


# --------------------------------------------------------------------------- #
# Injected interfaces                                                          #
# --------------------------------------------------------------------------- #


@runtime_checkable
class ConditionEvaluator(Protocol):
    """Returns True when the tick satisfies the setup's entry conditions."""

    def evaluate(self, tick: Tick, setup: Setup) -> bool: ...


@runtime_checkable
class TelegramNotifier(Protocol):
    async def send_proposal(self, proposal: ActiveProposal) -> None: ...
    async def send_invalidation(self, proposal_id: str, reason: str) -> None: ...
    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> None: ...


@runtime_checkable
class DecisionLogger(Protocol):
    async def log_proposal(self, proposal: ActiveProposal) -> None: ...

    async def log_decision(
        self,
        proposal: ActiveProposal,
        decision: str,
        reject_reason: Optional[str] = None,
    ) -> None: ...


# --------------------------------------------------------------------------- #
# Pure helpers                                                                 #
# --------------------------------------------------------------------------- #

_JPY_QUOTED = frozenset({"JPY", "HUF", "KRW"})


def _pip_size(symbol: str) -> float:
    """0.01 for JPY-quoted pairs, 0.0001 for everything else."""
    return 0.01 if symbol[-3:].upper() in _JPY_QUOTED else 0.0001


def compute_sl_price(
    entry: float, direction: Side, stop_pips: float, symbol: str
) -> float:
    """Absolute SL price from entry and stop distance in pips."""
    dist = stop_pips * _pip_size(symbol)
    return entry - dist if direction == "long" else entry + dist


def compute_tp_prices(
    entry: float,
    direction: Side,
    sl_price: float,
    tp_legs: list[Any],
    symbol: str,
) -> list[float]:
    """TP prices from the exit spec legs.

    V0 supports 'rr' and 'fixed_pips' models. 'atr' falls back to 1:1 RR
    because bar data is not available in the tick-only feed.
    """
    sl_dist = abs(entry - sl_price)
    pip = _pip_size(symbol)
    prices: list[float] = []
    for leg in tp_legs:
        if leg.model == "rr":
            dist = leg.value * sl_dist
        elif leg.model == "fixed_pips":
            dist = leg.value * pip
        else:
            dist = sl_dist  # atr fallback
        prices.append(entry + dist if direction == "long" else entry - dist)
    return prices


def circuit_breaker_tripped(
    tick: Tick, proposal: ActiveProposal, fraction: float
) -> bool:
    """True if the current price has moved adversely past `fraction` of the stop
    distance from the proposal's entry price."""
    current = tick.fill_price(proposal.direction)
    threshold = fraction * proposal.sl_distance
    if proposal.direction == "long":
        return current < proposal.entry_price - threshold
    return current > proposal.entry_price + threshold


# --------------------------------------------------------------------------- #
# Serialization (for hot-state persistence)                                   #
# --------------------------------------------------------------------------- #


def _proposal_to_dict(p: ActiveProposal) -> dict[str, Any]:
    return {
        "proposal_id": p.proposal_id,
        "strategy_id": p.strategy_id,
        "symbol": p.symbol,
        "direction": p.direction,
        "entry_price": p.entry_price,
        "stop_loss_price": p.stop_loss_price,
        "take_profit_prices": p.take_profit_prices,
        "confidence_score": p.confidence_score,
        "rationale": p.rationale,
        "proposed_at": p.proposed_at.isoformat(),
        "expires_at": p.expires_at.isoformat(),
        "sl_distance": p.sl_distance,
    }


# --------------------------------------------------------------------------- #
# Agent loop                                                                   #
# --------------------------------------------------------------------------- #


class AgentLoop:
    """Single-strategy agent execution loop.

    One instance per deployed strategy. Wires the pure state machine to live
    I/O (broker, hot state, Telegram, decision logger).

    Thread-safety: single-threaded async. Do not call from multiple coroutines.
    """

    def __init__(
        self,
        spec: StrategySpec,
        broker: BrokerAdapter,
        state_store: StateStore,
        telegram: TelegramNotifier,
        logger: DecisionLogger,
        evaluator: ConditionEvaluator,
        cooldown_seconds: int = 300,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.spec = spec
        self.broker = broker
        self.state_store = state_store
        self.telegram = telegram
        self.logger = logger
        self.evaluator = evaluator
        self.cooldown_seconds = cooldown_seconds
        self._now: Callable[[], datetime] = now_fn or (
            lambda: datetime.now(timezone.utc)
        )

        self._state = LoopState.FLAT
        self._proposal: Optional[ActiveProposal] = None
        self._open_position_id: Optional[str] = None
        self._cooldown_until: Optional[datetime] = None

    @property
    def state(self) -> LoopState:
        return self._state

    # ---------------------------------------------------------------------- #
    # Public event handlers                                                   #
    # ---------------------------------------------------------------------- #

    async def on_tick(self, tick: Tick) -> None:
        """Process a price tick. Called by the price feed subscriber."""
        now = self._now()
        if self._state == LoopState.FLAT:
            await self._handle_flat(tick)
        elif self._state == LoopState.SEEKING:
            await self._handle_seeking(tick, now)
        elif self._state == LoopState.COOLDOWN:
            self._check_cooldown(now)
        # IN_POSITION: wait for on_position_closed; ticks do nothing

    async def on_approval(self, proposal_id: str, used_keys: set[str]) -> None:
        """Called by the Telegram callback handler when the trader approves.

        Re-checks the validity window before placing. Idempotency guard prevents
        double execution on duplicate callbacks.
        """
        if self._state != LoopState.SEEKING:
            return
        proposal = self._proposal
        if proposal is None or proposal.proposal_id != proposal_id:
            return

        now = self._now()
        if now >= proposal.expires_at:
            await self._invalidate(proposal, "approval arrived after validity window expired")
            return

        if not should_send({"proposal_id": proposal_id}, used_keys):
            return  # idempotency: client key already produced a broker order

        position = await self.broker.place_order(
            client_id=proposal_id,
            symbol=proposal.symbol,
            direction=proposal.direction,
            # V0: minimum lot. V1 will size from PerTradeRisk + live account balance.
            volume=0.01,
            stop_loss=proposal.stop_loss_price,
            take_profit=proposal.take_profit_prices,
        )

        await self.state_store.mark_idempotency_key(proposal_id)
        await self.state_store.delete_pending_proposal(proposal_id)
        # open-position flag stays set until the position closes
        await self.logger.log_decision(proposal, "approve")

        self._open_position_id = position.position_id
        self._proposal = None
        self._state = LoopState.IN_POSITION

    async def on_rejection(
        self, proposal_id: str, reason: Optional[str] = None
    ) -> None:
        """Called by the Telegram callback handler when the trader rejects."""
        if self._state != LoopState.SEEKING:
            return
        proposal = self._proposal
        if proposal is None or proposal.proposal_id != proposal_id:
            return

        await self.state_store.delete_pending_proposal(proposal_id)
        await self.state_store.clear_open_position_flag(
            self.spec.id, proposal.symbol
        )
        await self.logger.log_decision(proposal, "reject", reject_reason=reason)

        self._proposal = None
        self._state = LoopState.FLAT

    async def on_position_closed(self, position_id: str) -> None:
        """Called when the broker reports the position is closed (SL/TP or manual)."""
        if self._state != LoopState.IN_POSITION:
            return
        if self._open_position_id != position_id:
            return

        await self.state_store.clear_open_position_flag(
            self.spec.id, self.spec.instrument.symbol
        )
        self._open_position_id = None
        self._cooldown_until = self._now() + timedelta(seconds=self.cooldown_seconds)
        self._state = LoopState.COOLDOWN

    # ---------------------------------------------------------------------- #
    # Internal state handlers                                                 #
    # ---------------------------------------------------------------------- #

    async def _handle_flat(self, tick: Tick) -> None:
        for setup in self.spec.setups:
            if self.evaluator.evaluate(tick, setup):
                await self._enter_seeking(tick, setup)
                return  # one proposal at a time

    async def _enter_seeking(self, tick: Tick, setup: Setup) -> None:
        now = self._now()
        direction = setup.direction
        symbol = self.spec.instrument.symbol
        entry = tick.fill_price(direction)

        stop = setup.exit.stop_loss
        # V0: treats all stop models as fixed_pips (bar data not available in tick feed)
        sl_price = compute_sl_price(entry, direction, stop.value, symbol)
        sl_dist = abs(entry - sl_price)
        tp_prices = compute_tp_prices(
            entry, direction, sl_price, setup.exit.take_profit, symbol
        )

        expires_at = now + timedelta(
            seconds=self.spec.execution.validity_window_seconds
        )
        proposal_id = str(uuid.uuid4())

        proposal = ActiveProposal(
            proposal_id=proposal_id,
            strategy_id=self.spec.id,
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_loss_price=sl_price,
            take_profit_prices=tp_prices,
            confidence_score=0.7,  # V0 static; V1 will weight from condition scores
            rationale=(
                f"Setup '{setup.name}' conditions matched on "
                f"{self.spec.timeframes.entry}"
            ),
            proposed_at=now,
            expires_at=expires_at,
            sl_distance=sl_dist,
        )

        await self.state_store.put_pending_proposal(
            proposal_id,
            _proposal_to_dict(proposal),
            self.spec.execution.validity_window_seconds,
        )
        await self.state_store.set_open_position_flag(self.spec.id, symbol)
        await self.logger.log_proposal(proposal)
        await self.telegram.send_proposal(proposal)

        self._proposal = proposal
        self._state = LoopState.SEEKING

    async def _handle_seeking(self, tick: Tick, now: datetime) -> None:
        proposal = self._proposal
        assert proposal is not None

        if now >= proposal.expires_at:
            await self._invalidate(proposal, "validity window expired")
            return

        cb = self.spec.execution.circuit_breaker
        if circuit_breaker_tripped(tick, proposal, cb.slip_invalidate_fraction):
            await self._invalidate(
                proposal,
                "circuit breaker: price slipped past 50% of stop distance",
            )

    async def _invalidate(self, proposal: ActiveProposal, reason: str) -> None:
        await self.state_store.delete_pending_proposal(proposal.proposal_id)
        await self.state_store.clear_open_position_flag(
            self.spec.id, proposal.symbol
        )
        await self.telegram.send_invalidation(proposal.proposal_id, reason)
        await self.logger.log_decision(proposal, "invalidated")
        self._proposal = None
        self._state = LoopState.FLAT

    def _check_cooldown(self, now: datetime) -> None:
        if self._cooldown_until and now >= self._cooldown_until:
            self._cooldown_until = None
            self._state = LoopState.FLAT


# --------------------------------------------------------------------------- #
# Agent loop registry (Telegram webhook -> AgentLoop lookup)                  #
# --------------------------------------------------------------------------- #


@runtime_checkable
class AgentLoopRegistry(Protocol):
    """Resolves a pending proposal id to the AgentLoop that owns it.

    The Telegram webhook (api/routers/telegram.py) only receives a
    `proposal_id` in callback_query.data; this is how it finds the right loop
    to call on_approval/on_rejection on.
    """

    async def get_loop_for_proposal(self, proposal_id: str) -> Optional["AgentLoop"]: ...


class InMemoryAgentLoopRegistry:
    """One AgentLoop per deployed strategy, kept in process memory.

    Per CLAUDE.md ("the live process is disposable") this index is rebuildable:
    it is just `{strategy_id: AgentLoop}` for loops the live runner has started
    in THIS process; the proposal -> strategy lookup goes through each loop's
    StateStore (Postgres/Redis), not memory.
    """

    def __init__(self) -> None:
        self._loops: dict[str, AgentLoop] = {}

    def register(self, loop: AgentLoop) -> None:
        self._loops[loop.spec.id] = loop

    def unregister(self, strategy_id: str) -> None:
        self._loops.pop(strategy_id, None)

    async def get_loop_for_proposal(self, proposal_id: str) -> Optional[AgentLoop]:
        for loop in self._loops.values():
            if await loop.state_store.get_pending_proposal(proposal_id) is not None:
                return loop
        return None
