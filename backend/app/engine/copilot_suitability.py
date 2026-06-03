"""Pure Co-Pilot suitability check (CLAUDE.md "Execution mode fits timeframe").

Co-Pilot (semi-auto) needs the human approve/reject loop to finish well before the
circuit breaker (invalidate past `breaker_fraction` of the stop distance) would
fire. On low-timeframe / tight-stop setups, approval latency routinely trips the
breaker first — those setups belong to Full Auto (post-V0), not Co-Pilot. Flagging
them is correct behaviour, not a defect.

This is the PURE check, computed only from a setup's entry timeframe and its stop
distance (both already in the StrategySpec). No I/O. The Rule Builder UI surface
that consumes it is built in slice 4.

Model (a documented heuristic; every constant is configurable):

    estimated_seconds_to_breaker
        = breaker_fraction
        * stop_in_bar_ranges(stop, timeframe)
        * BAR_SECONDS[timeframe]
        * BAR_TRAVERSAL_FRACTION

A setup is suitable for Co-Pilot when that estimate is >= the assumed human
approval latency.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.contract.schemas import Setup, StopLoss, Timeframe

# --- Required configurable constants --------------------------------------- #
# End-to-end human approve/reject latency. CLAUDE.md: realistically 5 to 30+ s.
# Default to the conservative high end, so "suitable" means safe even on a slow
# approval.
DEFAULT_APPROVAL_LATENCY_SECONDS: float = 30.0
# Mirrors ExecutionSpec.circuit_breaker.slip_invalidate_fraction.
DEFAULT_BREAKER_FRACTION: float = 0.5

# --- Model constants (heuristic; configurable) ----------------------------- #
# Representative bar duration per entry timeframe, in seconds.
BAR_SECONDS: dict[str, float] = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800, "MN1": 2592000,
}
# During an adverse impulse price can traverse ~its whole bar range in a fraction
# of the bar's duration; this scales the "one bar range per bar" baseline.
BAR_TRAVERSAL_FRACTION: float = 0.25
# Typical bar range in pips for FX majors — only used to turn a FIXED-PIP stop into
# "bar ranges". A heuristic floor, not instrument-specific truth.
TYPICAL_BAR_RANGE_PIPS: dict[str, float] = {
    "M1": 2.0, "M5": 4.0, "M15": 8.0, "M30": 13.0,
    "H1": 20.0, "H4": 45.0, "D1": 90.0, "W1": 200.0, "MN1": 400.0,
}
# A stop "to structure" can't be measured here; treat it as ~one bar range.
STRUCTURE_STOP_BAR_RANGES: float = 1.0


@dataclass(frozen=True)
class CopilotSuitability:
    suitable: bool
    reason: str
    estimated_seconds_to_breaker: float
    assumed_latency_seconds: float


def _stop_in_bar_ranges(stop_loss: StopLoss, timeframe: Timeframe) -> float:
    if stop_loss.model == "atr":
        # An ATR multiple is already ~multiples of a typical bar range.
        return float(stop_loss.value)
    if stop_loss.model == "fixed_pips":
        return float(stop_loss.value) / TYPICAL_BAR_RANGE_PIPS[timeframe]
    # "structure": unmeasurable here.
    return STRUCTURE_STOP_BAR_RANGES


def estimated_seconds_to_breaker(
    stop_loss: StopLoss,
    entry_timeframe: Timeframe,
    breaker_fraction: float = DEFAULT_BREAKER_FRACTION,
) -> float:
    """Rough seconds before price moves `breaker_fraction` of the stop distance."""
    bars = _stop_in_bar_ranges(stop_loss, entry_timeframe)
    return breaker_fraction * bars * BAR_SECONDS[entry_timeframe] * BAR_TRAVERSAL_FRACTION


def assess_copilot_suitability(
    *,
    entry_timeframe: Timeframe,
    setup: Setup,
    approval_latency_seconds: float = DEFAULT_APPROVAL_LATENCY_SECONDS,
    breaker_fraction: float = DEFAULT_BREAKER_FRACTION,
) -> CopilotSuitability:
    """Pure suitability check for one setup.

    Higher timeframe + wider stop -> suitable; low timeframe + tight stop ->
    unsuitable for Co-Pilot (it needs Full Auto, a post-V0 capability).
    """
    eta = estimated_seconds_to_breaker(setup.exit.stop_loss, entry_timeframe, breaker_fraction)
    pct = int(round(breaker_fraction * 100))
    suitable = eta >= approval_latency_seconds
    if suitable:
        reason = (
            f"On {entry_timeframe}, price would take about {eta:.0f}s to reach the {pct}% "
            f"circuit breaker — comfortably longer than the ~{approval_latency_seconds:.0f}s a "
            "human approval realistically takes. Suitable for Co-Pilot."
        )
    else:
        reason = (
            f"On {entry_timeframe} with this stop, price would reach the {pct}% circuit breaker "
            f"in about {eta:.0f}s, but a human approval realistically takes "
            f"~{approval_latency_seconds:.0f}s. Co-Pilot would auto-invalidate before you could "
            "approve, so this setup is unsuitable for Co-Pilot — it needs Full Auto (a post-V0 "
            "capability), not semi-auto approval."
        )
    return CopilotSuitability(
        suitable=suitable,
        reason=reason,
        estimated_seconds_to_breaker=eta,
        assumed_latency_seconds=approval_latency_seconds,
    )
