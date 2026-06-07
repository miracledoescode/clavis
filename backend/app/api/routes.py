"""HTTP routes for the public API surface.

Authoring slice:
  GET  /health                       public liveness probe
  GET  /v1/api/me                    whoami (proves auth wiring)
  POST /v1/strategies/parse          natural language -> block | clarification | spec
  POST /v1/strategies                create (validate -> persist v1 + snapshot)
  PUT  /v1/strategies/{id}           edit (validate -> bump version + snapshot)
  GET  /v1/strategies                list the caller's strategies
  POST /v1/backtests                 queue a backtest
  GET  /v1/backtests/{id}            poll backtest status & report

Every route except /health requires a verified Supabase JWT. The bridge is never
mounted here — it is internal infrastructure.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.api.models import (
    BacktestRequest,
    CreateStrategyRequest,
    ParseRequest,
    UpdateStrategyRequest,
)
from app.contract.schemas import StrategySpec
from app.engine import backtest_store, strategy_engine
from app.engine.strategy_parser import parse_strategy

# Where the Dukascopy ingest writes its parquet store. Empty -> backtests error
# clearly ("run the ingest") rather than fabricate data.
BACKTEST_DATA_DIR = os.getenv("BACKTEST_DATA_DIR", "")

router = APIRouter(prefix="/v1")


def get_claude_call():
    """Provide the Claude callable as a dependency so tests can override it."""
    from app.integrations.claude import call_claude

    return call_claude


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/me", tags=["auth"])
async def me(principal: dict = Depends(get_current_user)) -> dict[str, str]:
    return {"user_id": principal["user_id"], "email": principal.get("email", "")}


@router.post("/strategies/parse", tags=["rule-builder"])
async def parse(
    req: ParseRequest,
    principal: dict = Depends(get_current_user),
    claude_call=Depends(get_claude_call),
) -> dict:
    """Translate the trader's words into a Strategy JSON (or block / clarify)."""
    return parse_strategy(req.text, claude_call=claude_call)


@router.post("/strategies", status_code=status.HTTP_201_CREATED, tags=["strategies"])
async def create_strategy(
    req: CreateStrategyRequest, principal: dict = Depends(get_current_user)
) -> dict:
    """Persist a validated strategy as version 1 under the caller's context."""
    spec = req.spec
    now = _now_iso()
    spec.metadata.author_user_id = principal["user_id"]
    spec.metadata.created_at = now
    spec.metadata.updated_at = now
    return await strategy_engine.create_strategy(
        user_id=principal["user_id"], name=req.name, spec=spec.model_dump(), token=principal["token"]
    )


@router.put("/strategies/{strategy_id}", tags=["strategies"])
async def update_strategy(
    strategy_id: str,
    req: UpdateStrategyRequest,
    principal: dict = Depends(get_current_user),
) -> dict:
    """Persist an edit: bump the version and snapshot it (RLS-scoped to owner)."""
    spec = req.spec
    spec.metadata.author_user_id = principal["user_id"]
    spec.metadata.updated_at = _now_iso()
    try:
        return await strategy_engine.update_strategy(
            strategy_id=strategy_id,
            name=req.name,
            spec=spec.model_dump(),
            token=principal["token"],
        )
    except strategy_engine.StrategyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")


@router.get("/strategies", tags=["strategies"])
async def list_strategies(principal: dict = Depends(get_current_user)) -> list:
    return await strategy_engine.list_strategies(token=principal["token"])


# --------------------------------------------------------------------------- #
# Backtest (in-process job + polling)                                          #
# --------------------------------------------------------------------------- #
def _compute_report(spec: dict, params: dict) -> dict:
    """Load local OHLCV and run the VectorBT worker. Lazy imports keep the heavy
    numeric stack off the app-import path; runs in a worker thread."""
    from app.engine.backtest_data import load_ohlcv
    from app.engine.backtest_worker import BacktestConfig, run_backtest

    if not BACKTEST_DATA_DIR:
        raise RuntimeError("BACKTEST_DATA_DIR is not configured; run the Dukascopy ingest first.")
    symbol = spec["instrument"]["symbol"]
    timeframe = spec["timeframes"]["entry"]
    df = load_ohlcv(symbol, timeframe, BACKTEST_DATA_DIR, start=params.get("start"), end=params.get("end"))
    overrides = params.get("cost_overrides") or {}
    return run_backtest(spec, df, BacktestConfig(**overrides) if overrides else None)


async def _run_backtest_job(backtest_id: str, spec: dict, params: dict, token: str) -> None:
    try:
        await backtest_store.update_backtest(backtest_id, token, status="running")
        report = await asyncio.to_thread(_compute_report, spec, params)
        await backtest_store.update_backtest(backtest_id, token, status="done", report=report)
    except Exception as exc:  # noqa: BLE001 - record the failure on the row; never crash
        await backtest_store.update_backtest(backtest_id, token, status="error", error=str(exc)[:500])


@router.post("/backtests", status_code=status.HTTP_202_ACCEPTED, tags=["backtest"])
async def create_backtest(
    req: BacktestRequest,
    background: BackgroundTasks,
    principal: dict = Depends(get_current_user),
) -> dict:
    """Queue a backtest of the caller's OWN strategy (RLS-scoped load)."""
    token = principal["token"]
    strategy = await backtest_store.get_strategy(req.strategy_id, token)
    if strategy is None:
        # RLS hides other users' strategies, so 'not found' also covers 'not yours'.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    try:
        StrategySpec.model_validate(strategy["strategy_spec"])  # an unvalidated spec never runs
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Strategy spec is invalid"
        )
    row = await backtest_store.create_backtest(
        user_id=principal["user_id"],
        strategy_id=req.strategy_id,
        strategy_version=strategy.get("version"),
        params=req.params or {},
        token=token,
    )
    background.add_task(_run_backtest_job, row["id"], strategy["strategy_spec"], req.params or {}, token)
    return {"id": row["id"], "status": row["status"]}


@router.get("/backtests/{backtest_id}", tags=["backtest"])
async def get_backtest(backtest_id: str, principal: dict = Depends(get_current_user)) -> dict:
    row = await backtest_store.get_backtest(backtest_id, principal["token"])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest not found")
    return row
