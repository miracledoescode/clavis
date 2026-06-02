/**
 * Clavis Strategy JSON  ::  TypeScript contract
 * schema_version: "1.0"
 *
 * This file is the SINGLE SOURCE OF TRUTH for what a strategy is.
 * It MUST stay in lockstep with backend/schemas.py. If you change a field
 * here, change it there in the same commit. The Rule Builder (React Flow)
 * compiles its canvas down to a StrategySpec; the engine executes only this.
 *
 * Design decisions baked in:
 *  - snake_case keys everywhere, so the serialized JSON is byte-identical
 *    whether produced by the frontend or the Python engine. No camel<->snake
 *    mapping layer to drift.
 *  - A strategy describes the FULL trade lifecycle (entry, exit, filters,
 *    risk, execution), not just entries.
 *  - Conditions are a tree of logical groups so the React Flow canvas maps
 *    cleanly onto the JSON.
 *  - Dangerous patterns (martingale, averaging down) are NOT first-class.
 *    They are guarded off by default in RiskGuards and must be explicitly,
 *    knowingly enabled. The completeness checker / classifier flags them
 *    before any code is generated.
 */

export const STRATEGY_SCHEMA_VERSION = "1.0" as const;

export type SchemaVersion = typeof STRATEGY_SCHEMA_VERSION;

/* ----------------------------------------------------------------------- */
/* Instrument                                                              */
/* ----------------------------------------------------------------------- */

export type AssetClass = "forex" | "metal" | "crypto_cfd" | "index_cfd";

export interface Instrument {
  /** Canonical symbol, broker-agnostic. e.g. "EURUSD", "XAUUSD", "BTCUSD". */
  symbol: string;
  asset_class: AssetClass;
  /**
   * Broker symbol suffix for the normalizer in the MT5 bridge.
   * Exness / Justmarkets append suffixes, e.g. "EURUSD.m" -> suffix ".m".
   * Null/omitted means no suffix.
   */
  broker_symbol_suffix?: string | null;
}

/* ----------------------------------------------------------------------- */
/* Timeframes                                                              */
/* ----------------------------------------------------------------------- */

export type Timeframe =
  | "M1" | "M5" | "M15" | "M30"
  | "H1" | "H4"
  | "D1" | "W1" | "MN1";

export type Direction = "long" | "short" | "both";

/**
 * Multi-timeframe roles. A strategy reasons across a higher-timeframe bias,
 * an intermediate structure timeframe, and an entry timeframe. All optional
 * except entry, so a single-timeframe strategy is still valid.
 */
export interface Timeframes {
  bias?: Timeframe | null;
  structure?: Timeframe | null;
  entry: Timeframe;
}

/* ----------------------------------------------------------------------- */
/* Conditions  (discriminated union on `kind`)                             */
/* ----------------------------------------------------------------------- */

export type Comparator =
  | "gt" | "gte" | "lt" | "lte" | "eq" | "crosses_above" | "crosses_below";

export type Bias = "bullish" | "bearish" | "neutral";

export interface IndicatorCondition {
  kind: "indicator";
  /** e.g. "ema", "rsi", "atr", "macd". */
  indicator: string;
  /** Indicator parameters, e.g. { period: 200 }. */
  params: Record<string, number | string | boolean>;
  comparator: Comparator;
  /** Compare against a literal value... */
  value?: number | null;
  /** ...or against another series, e.g. "price.close" or "ema(50)". */
  reference?: string | null;
  timeframe?: Timeframe | null;
}

export interface StructureCondition {
  kind: "structure";
  event: "break_of_structure" | "change_of_character" | "liquidity_sweep";
  timeframe: Timeframe;
}

export interface CandlestickCondition {
  kind: "candlestick";
  pattern:
    | "bullish_engulfing"
    | "bearish_engulfing"
    | "pin_bar"
    | "inside_bar"
    | "doji";
  timeframe: Timeframe;
}

export interface BiasCondition {
  kind: "bias";
  timeframe: Timeframe;
  bias: Bias;
}

export interface PriceLevelCondition {
  kind: "price_level";
  level_type: "support" | "resistance" | "round_number" | "prior_day_high" | "prior_day_low";
  comparator: Comparator;
  /** Optional explicit price; otherwise the level is derived at runtime. */
  value?: number | null;
}

export type Condition =
  | IndicatorCondition
  | StructureCondition
  | CandlestickCondition
  | BiasCondition
  | PriceLevelCondition;

export type LogicalOperator = "all" | "any";

export interface ConditionGroup {
  operator: LogicalOperator;
  children: Array<Condition | ConditionGroup>;
}

/* ----------------------------------------------------------------------- */
/* Confluence  (optional scoring layer)                                    */
/* ----------------------------------------------------------------------- */

/**
 * Confluence lets a strategy require a weighted score rather than a hard
 * boolean. Each factor contributes weight when its condition is true; the
 * trade is valid only when the summed score meets `min_score`.
 */
export interface ConfluenceFactor {
  label: string;
  weight: number;
  condition: Condition | ConditionGroup;
}

export interface Confluence {
  min_score: number;
  factors: ConfluenceFactor[];
}

/* ----------------------------------------------------------------------- */
/* Entry / Exit                                                            */
/* ----------------------------------------------------------------------- */

export interface EntrySpec {
  /** Hard entry conditions (always required). */
  conditions: ConditionGroup;
  /** Optional weighted confluence layer on top of the hard conditions. */
  confluence?: Confluence | null;
}

export type StopModel = "fixed_pips" | "atr" | "structure";

export interface StopLoss {
  model: StopModel;
  /** pips for fixed_pips; multiplier for atr; ignored for structure. */
  value: number;
  /** ATR period when model = "atr". */
  atr_period?: number | null;
}

export type TakeProfitModel = "rr" | "fixed_pips" | "atr";

export interface TakeProfitLeg {
  model: TakeProfitModel;
  /** R multiple for "rr"; pips for "fixed_pips"; ATR multiple for "atr". */
  value: number;
  /**
   * Percentage of position to close at this leg (0-100). Multiple legs =
   * partial closes. NOTE: partial closes are a Titan-tier capability; the
   * Tier Enforcer rejects multi-leg take profit below Titan.
   */
  close_percent: number;
}

export interface TrailingStop {
  enabled: boolean;
  model: "atr" | "fixed_pips" | "structure";
  value: number;
  /** Only start trailing after price reaches this R multiple. */
  activate_at_rr?: number | null;
}

export interface BreakEven {
  enabled: boolean;
  /** Move stop to entry once price reaches this R multiple. */
  trigger_rr: number;
  /** Optional lock-in offset in pips beyond entry. */
  offset_pips?: number | null;
}

export interface ExitSpec {
  stop_loss: StopLoss;
  take_profit: TakeProfitLeg[];
  /** Trade-management features below are Navigator+ / Titan tier. */
  trailing_stop?: TrailingStop | null;
  break_even?: BreakEven | null;
}

/* ----------------------------------------------------------------------- */
/* Filters                                                                 */
/* ----------------------------------------------------------------------- */

export type TradingSession = "sydney" | "tokyo" | "london" | "new_york";

export interface SessionFilter {
  enabled: boolean;
  allowed_sessions: TradingSession[];
}

export interface NewsFilter {
  enabled: boolean;
  block_high_impact: boolean;
  minutes_before: number;
  minutes_after: number;
  /** Currency codes to watch, e.g. ["USD", "EUR"]. Empty = symbol currencies. */
  currencies: string[];
}

export interface TimeFilter {
  enabled: boolean;
  /** 0 = Sunday ... 6 = Saturday. */
  allowed_days: number[];
  /** Inclusive UTC hour window [start, end), 0-23. */
  allowed_hours_utc: { start: number; end: number };
}

export interface Filters {
  sessions?: SessionFilter | null;
  news?: NewsFilter | null;
  time?: TimeFilter | null;
}

/* ----------------------------------------------------------------------- */
/* Risk                                                                    */
/* ----------------------------------------------------------------------- */

export type PerTradeRiskModel = "fixed_percent" | "fixed_amount" | "atr_based";

export interface PerTradeRisk {
  model: PerTradeRiskModel;
  /** percent of account for fixed_percent; absolute for fixed_amount. */
  value: number;
  /** Hard ceiling on lot size regardless of model. */
  max_lot?: number | null;
}

export interface SessionRisk {
  max_trades?: number | null;
  max_loss_percent?: number | null;
  max_consecutive_losses?: number | null;
}

export interface AccountRisk {
  max_drawdown_percent?: number | null;
  max_open_positions?: number | null;
  daily_loss_limit_percent?: number | null;
}

/**
 * Hard guards against self-destructive patterns. Default DENY. Flipping any
 * of these to true is a deliberate, logged action and trips the dangerous-
 * vagueness classifier for human review.
 */
export interface RiskGuards {
  disallow_martingale: boolean;     // default true
  disallow_averaging_down: boolean; // default true
  disallow_grid: boolean;           // default true
}

export interface RiskSpec {
  per_trade: PerTradeRisk;
  session?: SessionRisk | null;
  account?: AccountRisk | null;
  guards: RiskGuards;
}

/* ----------------------------------------------------------------------- */
/* Execution                                                               */
/* ----------------------------------------------------------------------- */

export type ExecutionMode = "full_manual" | "semi_auto" | "full_auto";

/**
 * Circuit breaker: while a proposal is pending approval, if price slips
 * beyond `slip_invalidate_fraction` of the stop distance, the proposal
 * auto-invalidates. Notion V0 spec: 0.5 (50 percent of stop distance).
 */
export interface CircuitBreaker {
  slip_invalidate_fraction: number;
}

export interface ExecutionSpec {
  mode: ExecutionMode;
  /** Proposal validity window. Notion V0 spec: 300 (5 minutes). */
  validity_window_seconds: number;
  circuit_breaker: CircuitBreaker;
  /**
   * SAFETY RULE (non-negotiable): SL and TP are always set on the order at
   * the broker, never only inside the Clavis loop. An outage must never
   * leave an unmanaged position. Engine enforces this regardless of flag,
   * but it is surfaced here for auditability.
   */
  broker_managed_sl_tp: true;
}

/* ----------------------------------------------------------------------- */
/* Top-level StrategySpec                                                  */
/* ----------------------------------------------------------------------- */

export interface StrategyMetadata {
  created_at: string;  // ISO 8601
  updated_at: string;  // ISO 8601
  author_user_id: string;
  /** Free text origin, e.g. the natural language the trader typed. */
  source_prompt?: string | null;
}

export interface StrategySpec {
  schema_version: SchemaVersion;
  id: string;
  name: string;
  description?: string | null;

  instrument: Instrument;
  timeframes: Timeframes;
  direction: Direction;

  entry: EntrySpec;
  exit: ExitSpec;
  filters: Filters;
  risk: RiskSpec;
  execution: ExecutionSpec;

  /** Monotonic version, mirrors strategies.version in Postgres. */
  version: number;
  metadata: StrategyMetadata;
}

/* ----------------------------------------------------------------------- */
/* Agent decision capture  (the RLHF seam -> agent_logs)                   */
/* ----------------------------------------------------------------------- */

export type UserDecision = "approve" | "reject" | "invalidated" | "executed";

export type RejectReasonChip =
  | "bad_timing"
  | "wrong_direction"
  | "news_risk"
  | "already_in_trade"
  | "low_conviction"
  | "spread_too_wide"
  | "other";

export interface AgentProposal {
  strategy_id: string;
  symbol: string;
  direction: Exclude<Direction, "both">;
  entry_price: number;
  stop_loss_price: number;
  take_profit_prices: number[];
  confidence_score: number; // 0-1
  rationale: string;
  proposed_at: string; // ISO 8601
  expires_at: string;  // ISO 8601, proposed_at + validity_window
}

export interface AgentDecisionLog {
  proposal: AgentProposal;
  user_decision: UserDecision;
  reject_reason_chip?: RejectReasonChip | null;
  confidence_score: number;
  /** Whether this row is eligible to enter the V1 training set. */
  training_flag: boolean;
  logged_at: string; // ISO 8601
}
