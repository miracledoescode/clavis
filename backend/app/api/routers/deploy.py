"""Deploy Hub — deploy / kill-switch / status for a strategy's live Agent.

  POST /v1/strategies/{strategy_id}/deploy   validate -> tier check -> flip
                                              deployment_status -> register loop
  POST /v1/strategies/{strategy_id}/stop     kill switch: flip deployment_status,
                                              unregister loop. Does NOT close open
                                              positions — SL/TP stay broker-managed
                                              (CLAUDE.md "SL/TP at the broker, always").
  GET  /v1/strategies/{strategy_id}/status   deployment_status + (if a live runner
                                              is running) the in-process loop state.

All reads/writes go through the caller's Supabase JWT (RLS-scoped) — an
unvalidated StrategySpec never runs.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.contract.schemas import StrategySpec
from app.engine import deploy_store, tier_enforcer
from app.engine.live_runner import LiveRunner

router = APIRouter(prefix="/v1/strategies", tags=["deploy-hub"])


def get_live_runner() -> Optional[LiveRunner]:
    """Wired to the live engine runner by main.py's lifespan when configured.

    Unlike get_agent_loop_registry, this returns None (not 503) when
    unconfigured: /status must still report `deployment_status` from Postgres
    in local dev / CI.
    """
    return None


@router.post("/{strategy_id}/deploy")
async def deploy(
    strategy_id: str,
    principal: dict = Depends(get_current_user),
    runner: Optional[LiveRunner] = Depends(get_live_runner),
) -> dict:
    token = principal["token"]
    row = await deploy_store.get_strategy(strategy_id, token)
    if row is None:
        # RLS hides other users' strategies, so 'not found' also covers 'not yours'.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    try:
        spec = StrategySpec.model_validate(row["strategy_spec"])
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Strategy spec is invalid"
        )

    current_live = await deploy_store.count_deployed(token, exclude_strategy_id=strategy_id)
    if not await tier_enforcer.check_live_agent_limit(principal["user_id"], current_live):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your plan's live Agent limit has been reached",
        )

    await deploy_store.set_deployment_status(strategy_id, "deployed", token)
    if runner is not None:
        await runner.deploy_strategy(strategy_id, spec)

    return {"id": strategy_id, "deployment_status": "deployed"}


@router.post("/{strategy_id}/stop")
async def stop(
    strategy_id: str,
    principal: dict = Depends(get_current_user),
    runner: Optional[LiveRunner] = Depends(get_live_runner),
) -> dict:
    token = principal["token"]
    row = await deploy_store.get_strategy(strategy_id, token)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    await deploy_store.set_deployment_status(strategy_id, "stopped", token)
    if runner is not None:
        await runner.stop_strategy(strategy_id)

    return {"id": strategy_id, "deployment_status": "stopped"}


@router.get("/{strategy_id}/status")
async def deploy_status(
    strategy_id: str,
    principal: dict = Depends(get_current_user),
    runner: Optional[LiveRunner] = Depends(get_live_runner),
) -> dict:
    token = principal["token"]
    row = await deploy_store.get_strategy(strategy_id, token)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    result = {"id": strategy_id, "deployment_status": row["deployment_status"]}
    if runner is not None:
        loop_state = runner.loop_state(strategy_id)
        result["loop_state"] = loop_state.name if loop_state is not None else None
    return result
