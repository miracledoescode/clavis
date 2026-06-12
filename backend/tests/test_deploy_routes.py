"""Deploy Hub routes: deploy / stop / status (test (d)).

`get_current_user` and `get_live_runner` are overridden via FastAPI
dependency_overrides; `deploy_store` / `tier_enforcer` Supabase calls are
monkeypatched directly (same module object the router imports), so no real
network/DB/Redis is needed.
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routers.deploy import get_live_runner
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
from app.engine import deploy_store, tier_enforcer
from app.engine.agent_loop import LoopState
from app.main import app

PRINCIPAL = {"user_id": "user-1", "token": "user-jwt"}


def _make_spec_dict() -> dict:
    return StrategySpec(
        id="strat-1",
        name="Test Strategy",
        instrument=Instrument(symbol="EURUSD", asset_class="forex"),
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
    ).model_dump()


class FakeRunner:
    def __init__(self, state: Optional[LoopState] = LoopState.FLAT) -> None:
        self.deploy_strategy = AsyncMock()
        self.stop_strategy = AsyncMock()
        self._state = state

    def loop_state(self, strategy_id: str) -> Optional[LoopState]:
        return self._state


@pytest.fixture(autouse=True)
def _override_user():
    app.dependency_overrides[get_current_user] = lambda: PRINCIPAL
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_live_runner, None)


@pytest.fixture
def client():
    return TestClient(app)


# --------------------------------------------------------------------------- #
# deploy                                                                       #
# --------------------------------------------------------------------------- #


def test_deploy_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        deploy_store, "get_strategy",
        AsyncMock(return_value={"id": "strat-1", "strategy_spec": _make_spec_dict(), "deployment_status": "stopped"}),
    )
    monkeypatch.setattr(deploy_store, "count_deployed", AsyncMock(return_value=0))
    monkeypatch.setattr(deploy_store, "set_deployment_status", AsyncMock(return_value={"id": "strat-1"}))
    monkeypatch.setattr(tier_enforcer, "check_live_agent_limit", AsyncMock(return_value=True))

    runner = FakeRunner()
    app.dependency_overrides[get_live_runner] = lambda: runner

    resp = client.post("/v1/strategies/strat-1/deploy")

    assert resp.status_code == 200
    assert resp.json() == {"id": "strat-1", "deployment_status": "deployed"}
    deploy_store.set_deployment_status.assert_awaited_once_with("strat-1", "deployed", "user-jwt")
    runner.deploy_strategy.assert_awaited_once()
    assert runner.deploy_strategy.call_args.args[0] == "strat-1"


def test_deploy_tier_limit_returns_403(client, monkeypatch):
    monkeypatch.setattr(
        deploy_store, "get_strategy",
        AsyncMock(return_value={"id": "strat-1", "strategy_spec": _make_spec_dict(), "deployment_status": "stopped"}),
    )
    monkeypatch.setattr(deploy_store, "count_deployed", AsyncMock(return_value=5))
    monkeypatch.setattr(deploy_store, "set_deployment_status", AsyncMock())
    monkeypatch.setattr(tier_enforcer, "check_live_agent_limit", AsyncMock(return_value=False))

    resp = client.post("/v1/strategies/strat-1/deploy")

    assert resp.status_code == 403
    deploy_store.set_deployment_status.assert_not_called()


def test_deploy_invalid_spec_returns_422(client, monkeypatch):
    monkeypatch.setattr(
        deploy_store, "get_strategy",
        AsyncMock(return_value={"id": "strat-1", "strategy_spec": {"not": "valid"}, "deployment_status": "stopped"}),
    )
    monkeypatch.setattr(deploy_store, "set_deployment_status", AsyncMock())

    resp = client.post("/v1/strategies/strat-1/deploy")

    assert resp.status_code == 422
    deploy_store.set_deployment_status.assert_not_called()


def test_deploy_not_found_returns_404(client, monkeypatch):
    monkeypatch.setattr(deploy_store, "get_strategy", AsyncMock(return_value=None))

    resp = client.post("/v1/strategies/strat-1/deploy")

    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# stop                                                                         #
# --------------------------------------------------------------------------- #


def test_stop_unregisters_loop(client, monkeypatch):
    monkeypatch.setattr(
        deploy_store, "get_strategy",
        AsyncMock(return_value={"id": "strat-1", "strategy_spec": _make_spec_dict(), "deployment_status": "deployed"}),
    )
    monkeypatch.setattr(deploy_store, "set_deployment_status", AsyncMock(return_value={"id": "strat-1"}))

    runner = FakeRunner()
    app.dependency_overrides[get_live_runner] = lambda: runner

    resp = client.post("/v1/strategies/strat-1/stop")

    assert resp.status_code == 200
    assert resp.json() == {"id": "strat-1", "deployment_status": "stopped"}
    deploy_store.set_deployment_status.assert_awaited_once_with("strat-1", "stopped", "user-jwt")
    runner.stop_strategy.assert_awaited_once_with("strat-1")


def test_stop_not_found_returns_404(client, monkeypatch):
    monkeypatch.setattr(deploy_store, "get_strategy", AsyncMock(return_value=None))

    resp = client.post("/v1/strategies/strat-1/stop")

    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# status                                                                       #
# --------------------------------------------------------------------------- #


def test_status_with_runner_includes_loop_state(client, monkeypatch):
    monkeypatch.setattr(
        deploy_store, "get_strategy",
        AsyncMock(return_value={"id": "strat-1", "strategy_spec": _make_spec_dict(), "deployment_status": "deployed"}),
    )

    runner = FakeRunner(state=LoopState.IN_POSITION)
    app.dependency_overrides[get_live_runner] = lambda: runner

    resp = client.get("/v1/strategies/strat-1/status")

    assert resp.status_code == 200
    assert resp.json() == {"id": "strat-1", "deployment_status": "deployed", "loop_state": "IN_POSITION"}


def test_status_without_runner_omits_loop_state(client, monkeypatch):
    monkeypatch.setattr(
        deploy_store, "get_strategy",
        AsyncMock(return_value={"id": "strat-1", "strategy_spec": _make_spec_dict(), "deployment_status": "stopped"}),
    )

    resp = client.get("/v1/strategies/strat-1/status")

    assert resp.status_code == 200
    assert resp.json() == {"id": "strat-1", "deployment_status": "stopped"}


def test_status_not_found_returns_404(client, monkeypatch):
    monkeypatch.setattr(deploy_store, "get_strategy", AsyncMock(return_value=None))

    resp = client.get("/v1/strategies/strat-1/status")

    assert resp.status_code == 404
