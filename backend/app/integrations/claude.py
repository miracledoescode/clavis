"""Claude API integration — strategy NLP parsing for the Rule Builder.

The Agent is a tool, not an advisor: it translates ONLY the trader's own described
logic into a Strategy JSON. The model default is claude-sonnet-4-6 (from config).
The Anthropic SDK is imported lazily so the module loads without an API key.
"""
from __future__ import annotations

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

DEFAULT_CLAUDE_MODEL: str = CLAUDE_MODEL

# The Agent translates the trader's words into Clavis Strategy JSON. It must never
# originate logic the trader did not author (keeps Clavis a tool, not an adviser).
SYSTEM_PROMPT = """You are the Clavis Rule Builder parser. A retail trader describes a trading \
strategy in plain language. Your ONLY job is to translate THE TRADER'S OWN described logic into a \
Clavis Strategy JSON (schema_version "1.0"). You are a tool, not an adviser: never invent, suggest, \
optimize, or add any strategy logic the trader did not state.

Output STRICT JSON only - no prose, no markdown, no code fences. The JSON MUST be exactly one of:

(1) Clarification - when any required field is missing or the intent is ambiguous:
{"type":"clarification","questions":[{"id":"<slug>","question":"<text>","why":"<why it's needed>"}]}

(2) Specification - ONLY when every required field is grounded in the trader's words:
{"type":"spec","spec":{ ...full StrategySpec... }}

StrategySpec shape (snake_case; all required unless marked optional):
- schema_version: "1.0"
- id: short slug (e.g. "ema-pullback")
- name: short human name
- description: optional string
- instrument: {symbol e.g. "EURUSD"; asset_class one of "forex"|"metal"|"index_cfd"; broker_symbol_suffix optional/null}
- timeframes: {entry: M1|M5|M15|M30|H1|H4|D1|W1|MN1; bias optional; structure optional}
- direction: "long"|"short"|"both"
- entry: {conditions: ConditionGroup; confluence optional/null}
- exit: {stop_loss:{model:"fixed_pips"|"atr"|"structure", value:number, atr_period optional}, take_profit:[{model:"rr"|"fixed_pips"|"atr", value:number, close_percent:0-100}]}
- filters: {sessions:null, news:null, time:null}  (use null unless the trader specified one)
- risk: {per_trade:{model:"fixed_percent"|"fixed_amount"|"atr_based", value:number}, guards:{disallow_martingale:true, disallow_averaging_down:true, disallow_grid:true}}
- execution: {mode:"semi_auto", validity_window_seconds:300, circuit_breaker:{slip_invalidate_fraction:0.5}, broker_managed_sl_tp:true}
- version: 1
- metadata: {created_at: ISO8601, updated_at: ISO8601, author_user_id: "", source_prompt: the trader's exact text}

ConditionGroup = {operator:"all"|"any", children:[Condition|ConditionGroup]}
Condition (discriminated by "kind"):
- {"kind":"indicator","indicator":"ema|sma|rsi|atr|macd|stochastic|...","params":{...numbers...},"comparator":"gt|gte|lt|lte|eq|crosses_above|crosses_below","value":number?,"reference":string?,"timeframe":TF?}
- {"kind":"structure","event":"break_of_structure|change_of_character|liquidity_sweep","timeframe":TF}
- {"kind":"candlestick","pattern":"bullish_engulfing|bearish_engulfing|pin_bar|inside_bar|doji","timeframe":TF}
- {"kind":"bias","timeframe":TF,"bias":"bullish|bearish|neutral"}
- {"kind":"price_level","level_type":"support|resistance|round_number|prior_day_high|prior_day_low","comparator":...,"value":number?}

HARD RULES:
- Encode only what the trader stated. If stop loss, take profit, risk, instrument, or timeframe were not given, ask (clarification) - never fabricate numbers.
- broker_managed_sl_tp must always be true.
- NEVER encode martingale, averaging-down / adding-to-losers, or grid/ladder logic. guards stay all true. If the trader asks for these, return a clarification stating Clavis blocks them - do not emit a spec.
- Crypto is unsupported. If the instrument is a cryptocurrency, return a clarification.
- Output JSON only."""


def call_claude(nl_text: str, *, model: str = DEFAULT_CLAUDE_MODEL) -> str:
    """Send the trader's text to Claude and return the raw JSON string reply.

    Raises RuntimeError if no API key is configured. The parse orchestrator
    injects this callable, so it can be mocked in tests.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set; the Rule Builder parse route needs a Claude API key."
        )
    import anthropic  # lazy import

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": nl_text}],
    )
    return "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
