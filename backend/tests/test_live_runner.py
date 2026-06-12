"""LiveRunner composition root (test (d)).

All I/O is faked: broker/state_store/telegram/logger/price_feed are
AsyncMocks (same style as tests/test_agent_loop.py's loop fixtures), and the
Supabase `strategies` lookup goes through httpx.MockTransport (same pattern
as tests/test_versioning.py). No real network/DB/Redis/MetaApi.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Callable
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

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
from app.engine.agent_loop import LoopState, Tick, _proposal_to_dict
from app.engine.live_runner import LiveRunner
from app.engine.live_state import BrokerPosition, ReconcileAction

run = asyncio.run

_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr("app.engine.live_runner.config.SUPABASE_REST_URL", "http://rest.test")
    monkeypatch.setattr("app.engine.live_runner.config.SUPABASE_SERVICE_ROLE_KEY", "service-key")


def _make_spec(strategy_id: str = "strat-1", symbol: str = "EURUSD") -> StrategySpec:
    return StrategySpec(
        id=strategy_id,
        name="Test Strategy",
        instrument=Instrument(symbol=symbol, asset_class="forex"),
        timeframes=Timeframes(entry="H1"),
        setups=[
            Setup(
                name="Test Setup",
                direction="long",
                entry=ConditionGroup(
                    operator="all",
                    children=[
                        IndicatorCondition(
                            kind="indicator", indicator="RSI", params={"period": 14},
                            comparator="lt", value=30.0,
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
            mode="semi_auto", validity_window_seconds=300,
            circuit_breaker=CircuitBreaker(slip_invalidate_fraction=0.5),
        ),
        version=1,
        metadata=StrategyMetadata(
            created_at="2026-06-09T00:00:00Z", updated_at="2026-06-09T00:00:00Z",
            author_user_id="user-1",
        ),
    )


def _make_proposal_dict(strategy_id: str = "strat-1", proposal_id: str = "p1", symbol: str = "EURUSD") -> dict:
    from app.engine.agent_loop import ActiveProposal

    return _proposal_to_dict(
        ActiveProposal(
            proposal_id=proposal_id,
            strategy_id=strategy_id,
            symbol=symbol,
            direction="long",
            entry_price=1.1000,
            stop_loss_price=1.0950,
            take_profit_prices=[1.1100],
            confidence_score=0.7,
            rationale="test",
            proposed_at=_T0,
            expires_at=_T0 + timedelta(minutes=5),
            sl_distance=0.005,
            user_id="user-1",
        )
    )


class FakePriceFeed:
    def __init__(self) -> None:
        self.connect = AsyncMock()
        self.subscribe = AsyncMock()
        self.aclose = AsyncMock()
        self._queue: asyncio.Queue[Tick] = asyncio.Queue()

    async def ticks(self):
        while True:
            yield await self._queue.get()


def _make_fakes(
    *,
    broker_positions: list[BrokerPosition] | None = None,
    pending_proposals: list[dict] | None = None,
):
    broker = MagicMock()
    broker.get_open_positions = AsyncMock(return_value=broker_positions or [])

    state_store = MagicMock()
    state_store.list_pending_proposals = AsyncMock(return_value=pending_proposals or [])
    state_store.get_pending_proposal = AsyncMock(return_value=None)
    state_store.set_open_position_flag = AsyncMock()
    state_store.clear_open_position_flag = AsyncMock()
    state_store.mark_idempotency_key = AsyncMock()
    state_store.delete_pending_proposal = AsyncMock()

    telegram = MagicMock()
    telegram.send_invalidation = AsyncMock()
    telegram.aclose = AsyncMock()

    decision_logger = MagicMock()
    decision_logger.log_decision = AsyncMock()
    decision_logger.aclose = AsyncMock()

    price_feed = FakePriceFeed()

    return broker, state_store, telegram, decision_logger, price_feed


def _make_runner(
    client: httpx.AsyncClient,
    *,
    now_fn: Callable[[], datetime] | None = None,
    **fake_kwargs,
) -> LiveRunner:
    broker, state_store, telegram, decision_logger, price_feed = _make_fakes(**fake_kwargs)
    return LiveRunner(
        broker=broker,
        state_store=state_store,
        telegram=telegram,
        decision_logger=decision_logger,
        price_feed=price_feed,
        client=client,
        now_fn=now_fn,
    )


def _rest_client(rows: list[dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/strategies")
        assert "deployment_status=eq.deployed" in str(request.url)
        return httpx.Response(200, json=rows)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- #
# start() — loads + registers deployed strategies                             #
# --------------------------------------------------------------------------- #


def test_start_loads_and_registers_deployed_strategies():
    spec = _make_spec()
    rows = [{"id": "strat-1", "strategy_spec": spec.model_dump()}]

    async def go():
        client = _rest_client(rows)
        runner = _make_runner(client)
        await runner.start()
        try:
            assert "strat-1" in runner._loops
            assert await runner.registry.get_loop_for_proposal("anything") is None  # no pending proposals
            runner._price_feed.subscribe.assert_awaited_once_with({"EURUSD"})
            runner._price_feed.connect.assert_awaited_once()
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


def test_start_skips_invalid_spec():
    rows = [{"id": "bad-1", "strategy_spec": {"not": "a valid spec"}}]

    async def go():
        client = _rest_client(rows)
        runner = _make_runner(client)
        await runner.start()
        try:
            assert runner._loops == {}
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


# --------------------------------------------------------------------------- #
# deploy_strategy / stop_strategy / loop_state                                 #
# --------------------------------------------------------------------------- #


def test_deploy_and_stop_strategy():
    spec = _make_spec()

    async def go():
        client = _rest_client([])
        runner = _make_runner(client)
        await runner.start()
        try:
            await runner.deploy_strategy("strat-1", spec)
            assert runner.loop_state("strat-1") == LoopState.FLAT
            runner._price_feed.subscribe.assert_awaited_with({"EURUSD"})

            await runner.stop_strategy("strat-1")
            assert runner.loop_state("strat-1") is None
            assert await runner.registry.get_loop_for_proposal("anything") is None
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


def test_deploy_strategy_is_idempotent():
    spec = _make_spec()

    async def go():
        client = _rest_client([])
        runner = _make_runner(client)
        await runner.start()
        try:
            await runner.deploy_strategy("strat-1", spec)
            await runner.deploy_strategy("strat-1", spec)
            assert len(runner._loops) == 1
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


# --------------------------------------------------------------------------- #
# Boot reconciliation — table-driven over reconcile() action kinds            #
# --------------------------------------------------------------------------- #


def test_reconcile_adopts_unknown_broker_position():
    spec = _make_spec()
    broker_positions = [
        BrokerPosition(position_id="B1", symbol="EURUSD", direction="long", volume=0.01, client_id=None)
    ]
    rows = [{"id": "strat-1", "strategy_spec": spec.model_dump()}]

    async def go():
        client = _rest_client(rows)
        runner = _make_runner(client, broker_positions=broker_positions)
        await runner.start()
        try:
            loop = runner._loops["strat-1"]
            assert loop.state == LoopState.IN_POSITION
            assert loop._open_position_id == "B1"
            runner._state_store.set_open_position_flag.assert_awaited_with("strat-1", "EURUSD")
            runner._logger.log_decision.assert_not_called()
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


def test_reconcile_adopt_with_matching_pending_proposal_logs_executed():
    spec = _make_spec()
    pending = _make_proposal_dict()
    broker_positions = [
        BrokerPosition(position_id="B1", symbol="EURUSD", direction="long", volume=0.01, client_id="p1")
    ]
    rows = [{"id": "strat-1", "strategy_spec": spec.model_dump()}]

    async def go():
        client = _rest_client(rows)
        runner = _make_runner(client, broker_positions=broker_positions, pending_proposals=[pending])
        await runner.start()
        try:
            loop = runner._loops["strat-1"]
            assert loop.state == LoopState.IN_POSITION
            assert loop._open_position_id == "B1"
            runner._state_store.mark_idempotency_key.assert_awaited_with("p1")
            runner._state_store.delete_pending_proposal.assert_awaited_with("p1")
            runner._logger.log_decision.assert_awaited_once()
            args = runner._logger.log_decision.call_args
            assert args.args[0].proposal_id == "p1"
            assert args.args[1] == "executed"
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


def test_reconcile_invalidates_expired_pending_proposal():
    spec = _make_spec()
    expired = _make_proposal_dict(proposal_id="p2")
    expired["expires_at"] = (_T0 - timedelta(minutes=1)).isoformat()  # already expired
    rows = [{"id": "strat-1", "strategy_spec": spec.model_dump()}]

    async def go():
        client = _rest_client(rows)
        runner = _make_runner(client, pending_proposals=[expired], now_fn=lambda: _T0)
        await runner.start()
        try:
            runner._state_store.delete_pending_proposal.assert_awaited_with("p2")
            runner._state_store.clear_open_position_flag.assert_awaited_with("strat-1", "EURUSD")
            runner._telegram.send_invalidation.assert_awaited_once()
            assert runner._telegram.send_invalidation.call_args.args[0] == "p2"
            runner._logger.log_decision.assert_awaited_once()
            args = runner._logger.log_decision.call_args
            assert args.args[0].proposal_id == "p2"
            assert args.args[1] == "invalidated"
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


def test_reconcile_noop_for_still_valid_pending_proposal():
    spec = _make_spec()
    valid = _make_proposal_dict(proposal_id="p3")
    valid["expires_at"] = (_T0 + timedelta(minutes=5)).isoformat()
    rows = [{"id": "strat-1", "strategy_spec": spec.model_dump()}]

    async def go():
        client = _rest_client(rows)
        runner = _make_runner(client, pending_proposals=[valid], now_fn=lambda: _T0)
        await runner.start()
        try:
            runner._state_store.delete_pending_proposal.assert_not_called()
            runner._telegram.send_invalidation.assert_not_called()
            runner._logger.log_decision.assert_not_called()
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


def test_apply_action_close_out_clears_flag_and_sets_cooldown():
    spec = _make_spec()

    async def go():
        client = _rest_client([])
        runner = _make_runner(client)
        await runner.start()
        try:
            await runner.deploy_strategy("strat-1", spec)
            loop = runner._loops["strat-1"]
            loop._state = LoopState.IN_POSITION
            loop._open_position_id = "B1"

            action = ReconcileAction(
                kind="close_out", target="position", reason="closed while down",
                broker_position_id="B1", symbol="EURUSD",
            )
            await runner._apply_action(loop, action, pending_by_id={})

            assert loop.state == LoopState.COOLDOWN
            assert loop._open_position_id is None
            runner._state_store.clear_open_position_flag.assert_awaited_with("strat-1", "EURUSD")
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


def test_apply_action_noop_does_nothing():
    spec = _make_spec()

    async def go():
        client = _rest_client([])
        runner = _make_runner(client)
        await runner.start()
        try:
            await runner.deploy_strategy("strat-1", spec)
            loop = runner._loops["strat-1"]
            action = ReconcileAction(kind="noop", target="proposal", reason="still valid", proposal_id="x")
            await runner._apply_action(loop, action, pending_by_id={})

            runner._state_store.delete_pending_proposal.assert_not_called()
            runner._telegram.send_invalidation.assert_not_called()
            runner._logger.log_decision.assert_not_called()
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


# --------------------------------------------------------------------------- #
# Tick routing                                                                 #
# --------------------------------------------------------------------------- #


def test_ticks_route_to_matching_loop():
    spec = _make_spec()
    rows = [{"id": "strat-1", "strategy_spec": spec.model_dump()}]

    async def go():
        client = _rest_client(rows)
        runner = _make_runner(client)
        await runner.start()
        try:
            loop = runner._loops["strat-1"]
            loop.on_tick = AsyncMock()

            tick = Tick(symbol="EURUSD", bid=1.1, ask=1.1002, timestamp=_T0)
            runner._price_feed._queue.put_nowait(tick)

            for _ in range(10):
                await asyncio.sleep(0)

            loop.on_tick.assert_awaited_with(tick)
        finally:
            await runner.stop()
            await client.aclose()

    run(go())


def test_ticks_for_other_symbol_not_routed():
    spec = _make_spec(symbol="EURUSD")
    rows = [{"id": "strat-1", "strategy_spec": spec.model_dump()}]

    async def go():
        client = _rest_client(rows)
        runner = _make_runner(client)
        await runner.start()
        try:
            loop = runner._loops["strat-1"]
            loop.on_tick = AsyncMock()

            tick = Tick(symbol="GBPUSD", bid=1.27, ask=1.2702, timestamp=_T0)
            runner._price_feed._queue.put_nowait(tick)

            for _ in range(10):
                await asyncio.sleep(0)

            loop.on_tick.assert_not_called()
        finally:
            await runner.stop()
            await client.aclose()

    run(go())
