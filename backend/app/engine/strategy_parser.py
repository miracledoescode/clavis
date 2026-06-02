"""Rule Builder parse orchestration.

Pipeline for a natural-language strategy description:
  1. DANGEROUS-VAGUENESS classifier (deterministic, runs BEFORE any model call):
     if the language implies martingale, averaging-down, or grid behaviour, block
     it with a plain-language warning. Nothing dangerous is ever encoded.
  2. Claude translates the trader's words into a candidate StrategySpec or asks
     structured clarifying questions (the Agent only encodes the user's logic).
  3. COMPLETENESS check: validate the candidate against the Pydantic contract
     (schemas.py). On failure, return what is missing - never a half-valid spec.
  4. Defence in depth: reject any spec whose RiskGuards are not all denied.

Returns a plain dict tagged by "type": block | clarification | incomplete | spec | error.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from pydantic import ValidationError

from app.contract.schemas import StrategySpec

# Deterministic patterns for the three guarded behaviours. Kept conservative and
# explainable; this is a guardrail, not a model.
_DANGEROUS_PATTERNS: dict[str, list[str]] = {
    "martingale": [
        r"\bmartingale\b",
        r"double(?:\s+\w+){0,3}\s+(?:after|on|following|each|every|per)\b[^.]*\bloss",
        r"double\s+(?:the\s+)?(?:lot|position|size|stake|bet)",
        r"increase\s+(?:lot|position|size|stake)[^.]*\bafter[^.]*\bloss",
    ],
    "averaging_down": [
        r"averag\w*\s+down",
        r"\badd(?:ing)?\s+to\s+(?:a\s+)?(?:los\w+|red)\b",
        r"buy\s+more\s+as\s+(?:it|price)\s+(?:falls|drops|goes\s+down)",
        r"scale\s+in\s+as\s+(?:it|price|the\s+trade)\s+(?:falls|drops|moves\s+against)",
        r"cost\s+averag",
    ],
    "grid": [
        r"\bgrid\b",
        r"ladder\s+of\s+(?:orders|trades|positions)",
        r"\bstack\s+orders\b",
        r"place\s+(?:orders|trades)\s+every\s+\d+\s*(?:pips?|points?)",
    ],
}


def classify_dangerous(nl_text: str) -> list[str]:
    """Return the guarded-pattern labels implied by the text (empty if clean)."""
    text = nl_text.lower()
    hits: list[str] = []
    for label, patterns in _DANGEROUS_PATTERNS.items():
        if any(re.search(p, text) for p in patterns):
            hits.append(label)
    return hits


_BLOCK_MESSAGES = {
    "martingale": "martingale (increasing size after losses)",
    "averaging_down": "averaging down (adding to a losing position)",
    "grid": "grid / ladder trading",
}


def _block_response(patterns: list[str]) -> dict[str, Any]:
    names = ", ".join(_BLOCK_MESSAGES.get(p, p) for p in patterns)
    return {
        "type": "block",
        "patterns": patterns,
        "message": (
            f"This description implies {names}. Clavis does not build these — they "
            "risk uncontrolled losses, so the risk guards stay on. Re-describe the "
            "strategy with a fixed stop loss and fixed per-trade risk instead."
        ),
    }


def _extract_json(raw: str) -> dict | None:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            try:
                return json.loads(s[i : j + 1])
            except Exception:
                return None
    return None


def _format_validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        out.append({"field": loc, "problem": err.get("msg", "invalid")})
    return out


def parse_strategy(nl_text: str, *, claude_call: Callable[[str], str]) -> dict[str, Any]:
    """Run the full parse pipeline. `claude_call(text) -> raw_json_str` is injected."""
    # 1. Dangerous-vagueness classifier — short-circuits before any model call.
    dangerous = classify_dangerous(nl_text)
    if dangerous:
        return _block_response(dangerous)

    # 2. Claude translates the trader's words.
    raw = claude_call(nl_text)
    data = _extract_json(raw)
    if data is None:
        return {
            "type": "error",
            "message": "Could not read a strategy from the response. Please rephrase.",
        }

    # Agent chose to ask for clarification.
    if data.get("type") == "clarification":
        return {"type": "clarification", "questions": data.get("questions", [])}

    candidate = data.get("spec") if data.get("type") == "spec" else data

    # 3. Completeness check against the contract.
    try:
        spec = StrategySpec.model_validate(candidate)
    except ValidationError as exc:
        return {
            "type": "incomplete",
            "missing": _format_validation_errors(exc),
            "message": "The strategy is missing or has invalid required fields. "
            "Add the details below and try again.",
        }

    # 4. Defence in depth: guards must remain fully denied.
    guards = spec.risk.guards
    if not (
        guards.disallow_martingale and guards.disallow_averaging_down and guards.disallow_grid
    ):
        return _block_response(["risk_guards_disabled"])

    return {"type": "spec", "spec": spec.model_dump()}
