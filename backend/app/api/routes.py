"""HTTP routes for the public API surface.

Authoring slice:
  GET  /health               public liveness probe
  GET  /api/me               whoami (proves auth wiring)
  POST /strategies/parse     natural language -> block | clarification | spec
  POST /strategies           create (validate -> persist v1 + snapshot)
  PUT  /strategies/{id}       edit (validate -> bump version + snapshot)
  GET  /strategies           list the caller's strategies

Every route except /health requires a verified Supabase JWT. The bridge is never
mounted here — it is internal infrastructure.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.api.models import CreateStrategyRequest, ParseRequest, UpdateStrategyRequest
from app.engine import strategy_engine
from app.engine.strategy_parser import parse_strategy

router = APIRouter()


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
    return {"user_id": principal["user_id"]}


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
