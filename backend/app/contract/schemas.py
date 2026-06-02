"""
Clavis Strategy JSON  ::  Python contract (Pydantic v2)
schema_version: "1.0"

This file is the backend half of the SINGLE SOURCE OF TRUTH. It MUST stay in
lockstep with frontend/types.ts. Field names are snake_case in both so the
serialized JSON is byte-identical in either direction; do not add aliases.

The FastAPI engine validates every inbound StrategySpec against these models
before it touches the agent loop. Anything that does not validate never runs.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

STRATEGY_SCHEMA_VERSION = "1.0"


class _Base(BaseModel):
    # Reject unknown keys: a typo in the contract should fail loudly, not
    # silently drop data. extra="forbid" is a cheap guard against drift.
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Instrument                                                                  #
# --------------------------------------------------------------------------- #

AssetClass = Literal["forex", "metal", "crypto_cfd", "index_cfd"]


class Instrument(_Base):
    symbol: str
    asset_class: AssetClass
    # Broker suffix for the MT5 symbol normalizer (e.g. "EURUSD.m" -> ".m").
    broker_symbol_suffix: Optional[str] = None


# --------------------------------------------------------------------------- #
# Timeframes                                                                  #
# --------------------------------------------------------------------------- #

Timeframe = Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
Direction = Literal["long", "short", "both"]


class Timeframes(_Base):
    bias: Optional[Timeframe] = None
    structure: Optional[Timeframe] = None
    entry: Timeframe


# --------------------------------------------------------------------------- #
# Conditions (discriminated union on `kind`)                                  #
# --------------------------------------------------------------------------- #

Comparator = Literal[
    "gt", "gte", "lt", "lte", "eq", "crosses_above", "crosses_below"
]
Bias = Literal["bullish", "bearish", "neutral"]


class IndicatorCondition(_Base):
    kind: Literal["indicator"] = "indicator"
    indicator: str
    params: dict[str, Union[float, str, bool]] = Field(default_factory=dict)
    comparator: Comparator
    value: Optional[float] = None
    reference: Optional[str] = None
    timeframe: Optional[Timeframe] = None


class StructureCondition(_Base):
    kind: Literal["structure"] = "structure"
    event: Literal["break_of_structure", "change_of_character", "liquidity_sweep"]
    timeframe: Timeframe


class CandlestickCondition(_Base):
    kind: Literal["candlestick"] = "candlestick"
    pattern: Literal[
        "bullish_engulfing", "bearish_engulfing", "pin_bar", "inside_bar", "doji"
    ]
    timeframe: Timeframe


class BiasCondition(_Base):
    kind: Literal["bias"] = "bias"
    timeframe: Timeframe
    bias: Bias


class PriceLevelCondition(_Base):
    kind: Literal["price_level"] = "price_level"
    level_type: Literal[
        "support", "resistance", "round_number", "prior_day_high", "prior_day_low"
    ]
    comparator: Comparator
    value: Optional[float] = None


Condition = Annotated[
    Union[
        IndicatorCondition,
        StructureCondition,
        CandlestickCondition,
        BiasCondition,
        PriceLevelCondition,
    ],
    Field(discriminator="kind"),
]

LogicalOperator = Literal["all", "any"]


class ConditionGroup(_Base):
    operator: LogicalOperator
    # Tree of conditions and nested groups. Mirrors the React Flow canvas.
    children: list[Union[Condition, "ConditionGroup"]]


# --------------------------------------------------------------------------- #
# Confluence                                                                  #
# --------------------------------------------------------------------------- #


class ConfluenceFactor(_Base):
    label: str
    weight: float
    condition: Union[Condition, ConditionGroup]


class Confluence(_Base):
    min_score: float
    factors: list[ConfluenceFactor]


# --------------------------------------------------------------------------- #
# Entry / Exit                                                                #
# --------------------------------------------------------------------------- #


class EntrySpec(_Base):
    conditions: ConditionGroup
    confluence: Optional[Confluence] = None


StopModel = Literal["fixed_pips", "atr", "structure"]


class StopLoss(_Base):
    model: StopModel
    value: float
    atr_period: Optional[int] = None


TakeProfitModel = Literal["rr", "fixed_pips", "atr"]


class TakeProfitLeg(_Base):
    model: TakeProfitModel
    value: float
    # Multiple legs == partial closes (Titan tier; Tier Enforcer gates this).
    close_percent: float = Field(ge=0, le=100)


class TrailingStop(_Base):
    enabled: bool
    model: Literal["atr", "fixed_pips", "structure"]
    value: float
    activate_at_rr: Optional[float] = None


class BreakEven(_Base):
    enabled: bool
    trigger_rr: float
    offset_pips: Optional[float] = None


class ExitSpec(_Base):
    stop_loss: StopLoss
    take_profit: list[TakeProfitLeg]
    trailing_stop: Optional[TrailingStop] = None
    break_even: Optional[BreakEven] = None


# --------------------------------------------------------------------------- #
# Filters                                                                     #
# --------------------------------------------------------------------------- #

TradingSession = Literal["sydney", "tokyo", "london", "new_york"]


class SessionFilter(_Base):
    enabled: bool
    allowed_sessions: list[TradingSession] = Field(default_factory=list)


class NewsFilter(_Base):
    enabled: bool
    block_high_impact: bool
    minutes_before: int
    minutes_after: int
    currencies: list[str] = Field(default_factory=list)


class HourWindow(_Base):
    start: int = Field(ge=0, le=23)
    end: int = Field(ge=0, le=23)


class TimeFilter(_Base):
    enabled: bool
    allowed_days: list[int] = Field(default_factory=list)  # 0=Sun .. 6=Sat
    allowed_hours_utc: HourWindow


class Filters(_Base):
    sessions: Optional[SessionFilter] = None
    news: Optional[NewsFilter] = None
    time: Optional[TimeFilter] = None


# --------------------------------------------------------------------------- #
# Risk                                                                        #
# --------------------------------------------------------------------------- #

PerTradeRiskModel = Literal["fixed_percent", "fixed_amount", "atr_based"]


class PerTradeRisk(_Base):
    model: PerTradeRiskModel
    value: float
    max_lot: Optional[float] = None


class SessionRisk(_Base):
    max_trades: Optional[int] = None
    max_loss_percent: Optional[float] = None
    max_consecutive_losses: Optional[int] = None


class AccountRisk(_Base):
    max_drawdown_percent: Optional[float] = None
    max_open_positions: Optional[int] = None
    daily_loss_limit_percent: Optional[float] = None


class RiskGuards(_Base):
    # Default DENY. Enabling any of these trips the dangerous-vagueness
    # classifier and requires explicit human confirmation.
    disallow_martingale: bool = True
    disallow_averaging_down: bool = True
    disallow_grid: bool = True


class RiskSpec(_Base):
    per_trade: PerTradeRisk
    session: Optional[SessionRisk] = None
    account: Optional[AccountRisk] = None
    guards: RiskGuards = Field(default_factory=RiskGuards)


# --------------------------------------------------------------------------- #
# Execution                                                                   #
# --------------------------------------------------------------------------- #

ExecutionMode = Literal["full_manual", "semi_auto", "full_auto"]


class CircuitBreaker(_Base):
    # V0 spec: 0.5 -> invalidate if price slips past 50% of stop distance.
    slip_invalidate_fraction: float = 0.5


class ExecutionSpec(_Base):
    mode: ExecutionMode
    validity_window_seconds: int = 300  # V0 spec: 5 minute window
    circuit_breaker: CircuitBreaker = Field(default_factory=CircuitBreaker)
    # SAFETY RULE: SL/TP always at the broker. Engine enforces regardless.
    broker_managed_sl_tp: Literal[True] = True


# --------------------------------------------------------------------------- #
# Top-level StrategySpec                                                       #
# --------------------------------------------------------------------------- #


class StrategyMetadata(_Base):
    created_at: str
    updated_at: str
    author_user_id: str
    source_prompt: Optional[str] = None


class StrategySpec(_Base):
    schema_version: Literal["1.0"] = STRATEGY_SCHEMA_VERSION
    id: str
    name: str
    description: Optional[str] = None

    instrument: Instrument
    timeframes: Timeframes
    direction: Direction

    entry: EntrySpec
    exit: ExitSpec
    filters: Filters = Field(default_factory=Filters)
    risk: RiskSpec
    execution: ExecutionSpec

    version: int
    metadata: StrategyMetadata


# --------------------------------------------------------------------------- #
# Agent decision capture (the RLHF seam -> agent_logs)                         #
# --------------------------------------------------------------------------- #

UserDecision = Literal["approve", "reject", "invalidated", "executed"]
RejectReasonChip = Literal[
    "bad_timing",
    "wrong_direction",
    "news_risk",
    "already_in_trade",
    "low_conviction",
    "spread_too_wide",
    "other",
]


class AgentProposal(_Base):
    strategy_id: str
    symbol: str
    direction: Literal["long", "short"]
    entry_price: float
    stop_loss_price: float
    take_profit_prices: list[float]
    confidence_score: float = Field(ge=0, le=1)
    rationale: str
    proposed_at: str
    expires_at: str


class AgentDecisionLog(_Base):
    proposal: AgentProposal
    user_decision: UserDecision
    reject_reason_chip: Optional[RejectReasonChip] = None
    confidence_score: float = Field(ge=0, le=1)
    training_flag: bool = False
    logged_at: str


# Resolve the forward reference in ConditionGroup.children.
ConditionGroup.model_rebuild()
