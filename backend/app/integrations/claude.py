"""Claude API integration — strategy NLP parsing and the Agent's reasoning.

The default model string is sourced from ``app.config`` (CLAUDE.md mandates
``claude-sonnet-4-6``). The Anthropic SDK is intentionally not a dependency yet.
Scaffold stub — not implemented.
"""
from __future__ import annotations

from app.config import CLAUDE_MODEL

# Single source of truth for the default model lives in app.config.
DEFAULT_CLAUDE_MODEL: str = CLAUDE_MODEL
