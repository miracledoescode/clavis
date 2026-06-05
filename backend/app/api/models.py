"""API request models for the authoring slice.

`CreateStrategyRequest.spec` and `UpdateStrategyRequest.spec` are typed as the
contract's `StrategySpec`, so FastAPI validates every inbound spec against
schemas.py at the boundary — an invalid spec is rejected (422) before any write.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.contract.schemas import StrategySpec


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class CreateStrategyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    spec: StrategySpec


class UpdateStrategyRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    spec: StrategySpec


class BacktestRequest(BaseModel):
    """Backtest a saved strategy. `params` may carry window (start/end) + cost overrides."""

    strategy_id: str
    params: Optional[dict] = None
