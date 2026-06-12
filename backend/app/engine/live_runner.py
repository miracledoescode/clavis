"""Live runner: composition root for the slice-4 live loop.

Builds the shared adapters (broker, hot state, telegram, decision logger,
price feed), loads every strategy with `deployment_status = 'deployed'`, runs
boot reconciliation per strategy (CLAUDE.md "State and Recovery"), and
registers one AgentLoop per strategy in InMemoryAgentLoopRegistry. A
background task drains the price feed and routes each tick to every loop
watching that symbol.

"The live process is disposable" — `start()` rebuilds everything from the
broker + Postgres + Redis; nothing here is authoritative. All adapters can be
injected (tests pass fakes); when omitted, real ones are built from `config`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import httpx
from pydantic import ValidationError

from app import config
from app.bridge.broker import MetaApiBrokerAdapter
from app.bridge.price_feed import MetaApiPriceFeed
from app.contract.schemas import StrategySpec
from app.engine.agent_loop import (
    AgentLoop,
    InMemoryAgentLoopRegistry,
    LoopState,
    _dict_to_proposal,
)
from app.engine.condition_evaluator import LiveConditionEvaluator
from app.engine.copilot import SupabaseDecisionLogger
from app.engine.hot_state import UpstashRedisStore
from app.engine.live_state import ExpectedState, PendingProposal, ReconcileAction
from app.engine.reconciliation import reconcile
from app.integrations.telegram import TelegramBotNotifier

logger = logging.getLogger(__name__)


def _service_headers() -> dict[str, str]:
    return {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
    }


def _url(path: str) -> str:
    return f"{config.SUPABASE_REST_URL}/{path}"


class LiveRunner:
    """One process-wide instance, started/stopped by `main.py`'s lifespan."""

    def __init__(
        self,
        *,
        broker: Optional[Any] = None,
        state_store: Optional[Any] = None,
        telegram: Optional[Any] = None,
        decision_logger: Optional[Any] = None,
        price_feed: Optional[Any] = None,
        client: Optional[httpx.AsyncClient] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.registry = InMemoryAgentLoopRegistry()
        self._broker = broker
        self._state_store = state_store
        self._telegram = telegram
        self._logger = decision_logger
        self._price_feed = price_feed
        self._client = client
        self._now: Callable[[], datetime] = now_fn or (lambda: datetime.now(timezone.utc))

        self._loops: dict[str, AgentLoop] = {}
        self._subscribed: set[str] = set()
        self._tick_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # Lazy adapter construction (overridable for tests)                   #
    # ------------------------------------------------------------------ #

    def _build_broker(self) -> Any:
        return MetaApiBrokerAdapter(
            config.METAAPI_TOKEN, config.METAAPI_ACCOUNT_ID, config.METAAPI_SYMBOL_SUFFIX or None
        )

    def _build_state_store(self) -> Any:
        return UpstashRedisStore()

    def _build_telegram(self) -> Any:
        return TelegramBotNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    def _build_logger(self) -> Any:
        return SupabaseDecisionLogger()

    def _build_price_feed(self) -> Any:
        return MetaApiPriceFeed(
            config.METAAPI_TOKEN, config.METAAPI_ACCOUNT_ID, config.METAAPI_SYMBOL_SUFFIX or None
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        self._broker = self._broker or self._build_broker()
        self._state_store = self._state_store or self._build_state_store()
        self._telegram = self._telegram or self._build_telegram()
        self._logger = self._logger or self._build_logger()
        self._price_feed = self._price_feed or self._build_price_feed()

        await self._price_feed.connect()

        for row in await self._fetch_deployed_strategies():
            try:
                spec = StrategySpec.model_validate(row["strategy_spec"])
            except ValidationError:
                # An unvalidated spec never runs (CLAUDE.md).
                logger.warning("live runner: skipping strategy %s — invalid spec", row.get("id"))
                continue
            await self._start_loop(spec)

        self._tick_task = asyncio.create_task(self._route_ticks())

    async def stop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None

        if self._price_feed is not None:
            await self._price_feed.aclose()
        if self._telegram is not None:
            await self._telegram.aclose()
        if self._logger is not None:
            await self._logger.aclose()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ #
    # Strategy loading                                                     #
    # ------------------------------------------------------------------ #

    async def _fetch_deployed_strategies(self) -> list[dict]:
        c = await self._get_client()
        resp = await c.get(
            _url("strategies"),
            headers=_service_headers(),
            params={"deployment_status": "eq.deployed", "select": "id,strategy_spec"},
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Per-strategy loop lifecycle                                          #
    # ------------------------------------------------------------------ #

    async def _start_loop(self, spec: StrategySpec) -> None:
        evaluator = LiveConditionEvaluator(spec.instrument.symbol, spec.timeframes.entry)
        loop = AgentLoop(
            spec=spec,
            broker=self._broker,
            state_store=self._state_store,
            telegram=self._telegram,
            logger=self._logger,
            evaluator=evaluator,
        )
        await self._reconcile_loop(loop)
        self.registry.register(loop)
        self._loops[spec.id] = loop

        symbol = spec.instrument.symbol
        if symbol not in self._subscribed:
            await self._price_feed.subscribe({symbol})
            self._subscribed.add(symbol)

    async def deploy_strategy(self, strategy_id: str, spec: StrategySpec) -> None:
        """Build and register one more AgentLoop for immediate effect (Deploy Hub)."""
        if strategy_id in self._loops:
            return
        await self._start_loop(spec)

    async def stop_strategy(self, strategy_id: str) -> None:
        """Kill switch: unregister the loop. Does NOT touch open positions —
        SL/TP remain broker-managed (CLAUDE.md)."""
        self.registry.unregister(strategy_id)
        self._loops.pop(strategy_id, None)

    def loop_state(self, strategy_id: str) -> Optional[LoopState]:
        loop = self._loops.get(strategy_id)
        return loop.state if loop is not None else None

    # ------------------------------------------------------------------ #
    # Boot reconciliation                                                  #
    # ------------------------------------------------------------------ #

    async def _reconcile_loop(self, loop: AgentLoop) -> None:
        broker_positions = await self._broker.get_open_positions()
        pending_rows = await self._state_store.list_pending_proposals()
        pending_for_strategy = [p for p in pending_rows if p.get("strategy_id") == loop.spec.id]
        pending_by_id = {p["proposal_id"]: p for p in pending_for_strategy}

        expected = ExpectedState(
            # V0 has no separate "expected open position" durable record — a
            # broker position Clavis doesn't recognise is ADOPTED (never
            # duplicated); see `_apply_action`'s "adopt" branch.
            positions=[],
            pending_proposals=[
                PendingProposal(
                    proposal_id=p["proposal_id"],
                    symbol=p["symbol"],
                    expires_at=datetime.fromisoformat(p["expires_at"]),
                )
                for p in pending_for_strategy
            ],
        )
        for action in reconcile(broker_positions, expected, self._now()):
            await self._apply_action(loop, action, pending_by_id)

    async def _apply_action(
        self, loop: AgentLoop, action: ReconcileAction, pending_by_id: dict[str, dict]
    ) -> None:
        if action.kind == "adopt":
            if action.symbol != loop.spec.instrument.symbol:
                return  # belongs to another loop's symbol
            loop._open_position_id = action.broker_position_id
            loop._proposal = None
            loop._state = LoopState.IN_POSITION
            await self._state_store.set_open_position_flag(loop.spec.id, action.symbol)
            if action.proposal_id and action.proposal_id in pending_by_id:
                # The proposal we sent was approved and executed while we were
                # down, but the decision log + hot-state cleanup never ran.
                proposal = _dict_to_proposal(pending_by_id[action.proposal_id])
                await self._state_store.mark_idempotency_key(action.proposal_id)
                await self._state_store.delete_pending_proposal(action.proposal_id)
                await self._logger.log_decision(proposal, "executed")

        elif action.kind == "close_out":
            if action.symbol != loop.spec.instrument.symbol:
                return
            # TODO(v1): write the close-out outcome to execution_history.
            await self._state_store.clear_open_position_flag(loop.spec.id, action.symbol)
            loop._open_position_id = None
            loop._cooldown_until = self._now() + timedelta(seconds=loop.cooldown_seconds)
            loop._state = LoopState.COOLDOWN

        elif action.kind == "invalidate":
            if action.proposal_id not in pending_by_id:
                return
            proposal = _dict_to_proposal(pending_by_id[action.proposal_id])
            await self._state_store.delete_pending_proposal(action.proposal_id)
            await self._state_store.clear_open_position_flag(loop.spec.id, proposal.symbol)
            await self._telegram.send_invalidation(action.proposal_id, action.reason)
            await self._logger.log_decision(proposal, "invalidated")

        # "noop" -> nothing to do.

    # ------------------------------------------------------------------ #
    # Tick routing                                                         #
    # ------------------------------------------------------------------ #

    async def _route_ticks(self) -> None:
        async for tick in self._price_feed.ticks():
            for loop in self._loops.values():
                if loop.spec.instrument.symbol == tick.symbol:
                    await loop.on_tick(tick)
