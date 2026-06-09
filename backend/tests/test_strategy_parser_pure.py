"""Pure unit tests for strategy_parser functions.

Tests the deterministic, safety-critical pure functions in isolation
(no Claude, no HTTP, no FastAPI). Covers every branch of:

  - classify_dangerous     — each pattern variant, combinations, clean text
  - _extract_json           — clean, markdown-fenced, inline, malformed, edge cases
  - _pop_direction_inferences — stripping behaviour, edge cases, non-dict input
  - _build_setup_confirmations — correct pairing, default fallback, multiple setups

These are the load-bearing guardrails that run BEFORE any model call.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.engine.strategy_parser import (
    _build_setup_confirmations,
    _extract_json,
    _format_validation_errors,
    _pop_direction_inferences,
    classify_dangerous,
)
from app.contract.schemas import StrategySpec


# ============================================================================ #
# classify_dangerous  —  deterministic pattern matcher                         #
# ============================================================================ #

class TestClassifyDangerous:
    """Every regex pattern in _DANGEROUS_PATTERNS exercised individually."""

    # -- martingale patterns ------------------------------------------------- #

    def test_martingale_literal_word(self):
        assert classify_dangerous("use a martingale strategy") == ["martingale"]

    def test_martingale_case_insensitive(self):
        assert classify_dangerous("Martingale after loss") == ["martingale"]

    def test_martingale_double_after_loss(self):
        assert classify_dangerous("double my lot after a loss") == ["martingale"]

    def test_martingale_double_on_loss(self):
        assert classify_dangerous("double the position on every loss") == ["martingale"]

    def test_martingale_double_following_loss(self):
        assert classify_dangerous("double size following each loss") == ["martingale"]

    def test_martingale_double_per_loss(self):
        assert classify_dangerous("double per loss") == ["martingale"]

    def test_martingale_double_lot(self):
        assert classify_dangerous("double the lot after loss") == ["martingale"]

    def test_martingale_double_position(self):
        assert classify_dangerous("double my position after a loss") == ["martingale"]

    def test_martingale_double_stake(self):
        assert classify_dangerous("double stake on loss") == ["martingale"]

    def test_martingale_double_bet(self):
        assert classify_dangerous("double the bet") == ["martingale"]

    def test_martingale_increase_lot_after_loss(self):
        assert classify_dangerous("increase lot after a loss") == ["martingale"]

    def test_martingale_increase_position_after_loss(self):
        assert classify_dangerous("increase position size after loss") == ["martingale"]

    def test_martingale_increase_stake_after_loss(self):
        assert classify_dangerous("increase stake after every loss") == ["martingale"]

    # -- averaging down patterns --------------------------------------------- #

    def test_averaging_down_literal(self):
        assert classify_dangerous("averaging down on losers") == ["averaging_down"]

    def test_averaging_down_verb(self):
        assert classify_dangerous("average down as it drops") == ["averaging_down"]

    def test_averaging_down_gerund(self):
        assert classify_dangerous("averaging down the position") == ["averaging_down"]

    def test_add_to_loser(self):
        assert classify_dangerous("add to a loser") == ["averaging_down"]

    def test_add_to_losing_position(self):
        assert classify_dangerous("adding to a losing position") == ["averaging_down"]

    def test_add_to_red(self):
        assert classify_dangerous("add to red") == ["averaging_down"]

    def test_buy_more_as_it_falls(self):
        assert classify_dangerous("buy more as it falls") == ["averaging_down"]

    def test_buy_more_as_price_drops(self):
        assert classify_dangerous("buy more as price drops") == ["averaging_down"]

    def test_buy_more_as_price_goes_down(self):
        assert classify_dangerous("buy more as it goes down") == ["averaging_down"]

    def test_scale_in_as_it_falls(self):
        assert classify_dangerous("scale in as price falls") == ["averaging_down"]

    def test_scale_in_moves_against(self):
        assert classify_dangerous("scale in as the trade moves against me") == ["averaging_down"]

    def test_cost_average(self):
        assert classify_dangerous("cost averaging into position") == ["averaging_down"]

    # -- grid patterns ------------------------------------------------------- #

    def test_grid_literal(self):
        assert classify_dangerous("run a grid") == ["grid"]

    def test_grid_case_insensitive(self):
        assert classify_dangerous("Grid Trading") == ["grid"]

    def test_ladder_of_orders(self):
        assert classify_dangerous("place a ladder of orders") == ["grid"]

    def test_ladder_of_trades(self):
        assert classify_dangerous("ladder of trades") == ["grid"]

    def test_ladder_of_positions(self):
        assert classify_dangerous("ladder of positions") == ["grid"]

    def test_stack_orders(self):
        assert classify_dangerous("stack orders at levels") == ["grid"]

    def test_place_orders_every_x_pips(self):
        assert classify_dangerous("place orders every 10 pips") == ["grid"]

    def test_place_trades_every_x_points(self):
        assert classify_dangerous("place trades every 50 points") == ["grid"]

    # -- compound (multiple categories) -------------------------------------- #

    def test_martingale_and_grid_together(self):
        hits = classify_dangerous("martingale grid strategy")
        assert "martingale" in hits
        assert "grid" in hits

    def test_all_three_categories(self):
        hits = classify_dangerous(
            "martingale, averaging down, and grid trading are all dangerous"
        )
        assert "martingale" in hits
        assert "averaging_down" in hits
        assert "grid" in hits

    # -- clean text (no matches) --------------------------------------------- #

    def test_clean_text_returns_empty(self):
        assert classify_dangerous("long EURUSD when RSI crosses below 30") == []

    def test_clean_text_with_stop_loss(self):
        assert (
            classify_dangerous(
                "short GBPUSD on H4, 1% risk, 2 ATR stop, 3R target"
            )
            == []
        )

    def test_clean_empty_string(self):
        assert classify_dangerous("") == []

    def test_clean_whitespace(self):
        assert classify_dangerous("   ") == []

    def test_clean_special_chars(self):
        assert classify_dangerous("!@#$%^&*()") == []

    # -- false positive guard: partial matches should NOT trigger ------------ #

    def test_double_as_normal_adjective_not_trading(self):
        """'double' used as a normal adjective should not trigger martingale."""
        assert classify_dangerous("check the double top pattern") == []

    def test_average_as_normal_statistic(self):
        """'average' used in a non-trading context should not trigger."""
        assert classify_dangerous("average true range period 14") == []

    def test_add_to_watchlist_not_averaging(self):
        """'add to' + non-loss context should ideally not trigger."""
        # Current pattern requires "los" after "add to", so this is safe.
        assert classify_dangerous("add to watchlist") == []

    def test_scale_out_not_averaging(self):
        """'scale' without 'in as ... falls' should not trigger."""
        assert classify_dangerous("scale out of half the position at 2R") == []

    def test_grid_as_layout_not_trading(self):
        """'grid' used in a non-trading context — still triggers because the
        guardrail is conservative (word-level match). This is correct-by-design:
        the classifier favours false positives over false negatives."""
        assert "grid" in classify_dangerous("arrange the charts in a grid")


# ============================================================================ #
# _extract_json  —  parse JSON from Claude's raw output                        #
# ============================================================================ #

class TestExtractJson:

    def test_clean_json_object(self):
        result = _extract_json('{"type": "spec", "name": "test"}')
        assert result == {"type": "spec", "name": "test"}

    def test_markdown_fenced_json(self):
        raw = '```json\n{"type": "spec", "value": 42}\n```'
        assert _extract_json(raw) == {"type": "spec", "value": 42}

    def test_markdown_fenced_no_lang(self):
        raw = '```\n{"key": "val"}\n```'
        assert _extract_json(raw) == {"key": "val"}

    def test_json_with_leading_text(self):
        raw = 'Here is your strategy:\n{"type": "spec"}\nLet me know.'
        assert _extract_json(raw) == {"type": "spec"}

    def test_json_with_trailing_text(self):
        raw = '{"type":"spec"}\nEnd of message'
        assert _extract_json(raw) == {"type": "spec"}

    def test_nested_json_with_braces(self):
        raw = '{"outer": {"inner": ["a", "b"]}}'
        assert _extract_json(raw) == {"outer": {"inner": ["a", "b"]}}

    def test_json_with_escaped_braces(self):
        raw = '{"regex": "\\\\d{3}"}'
        result = _extract_json(raw)
        assert result is not None
        assert result["regex"] == "\\d{3}"

    def test_empty_string(self):
        assert _extract_json("") is None

    def test_malformed_json(self):
        assert _extract_json("this is not json at all") is None

    def test_broken_brace_json_no_fallback(self):
        """Unmatched braces — the fallback extraction should still try."""
        raw = '{"incomplete": true'
        result = _extract_json(raw)
        # First json.loads fails, then the fallback finds the substring
        assert result is None  # the substring { to } would fail too

    def test_partial_json_with_closing_brace(self):
        """A partially valid JSON fragment that json.loads can still eat."""
        raw = 'some text {"a": 1} trailing'
        result = _extract_json(raw)
        assert result == {"a": 1}

    def test_markdown_without_json(self):
        raw = "```python\nprint('hello')\n```"
        assert _extract_json(raw) is None

    def test_whitespace_only(self):
        assert _extract_json("   \n  ") is None

    def test_surrounding_triple_backtick_no_newline(self):
        raw = '```{"key": "val"}```'
        assert _extract_json(raw) == {"key": "val"}

    def test_clarification_response(self):
        raw = '{"type":"clarification","questions":[{"id":"tf","question":"Which tf?"}]}'
        result = _extract_json(raw)
        assert result is not None
        assert result["type"] == "clarification"
        assert len(result["questions"]) == 1


# ============================================================================ #
# _pop_direction_inferences  —  strip parse-time hints from candidate          #
# ============================================================================ #

class TestPopDirectionInferences:

    def test_strips_inferred_field(self):
        candidate = {
            "setups": [
                {"name": "long setup", "direction": "long",
                 "direction_inferred": True, "direction_rationale": "RSI low"},
            ]
        }
        inferences = _pop_direction_inferences(candidate)
        assert "direction_inferred" not in candidate["setups"][0]
        assert "direction_rationale" not in candidate["setups"][0]
        assert 0 in inferences
        assert inferences[0]["inferred"] is True
        assert inferences[0]["rationale"] == "RSI low"

    def test_explicit_direction_not_inferred(self):
        candidate = {
            "setups": [
                {"name": "s", "direction": "short",
                 "direction_inferred": False, "direction_rationale": "trader said short"},
            ]
        }
        inferences = _pop_direction_inferences(candidate)
        assert inferences[0]["inferred"] is False

    def test_missing_inferred_defaults_true(self):
        """When direction_inferred is absent, default to True (require confirmation)."""
        candidate = {"setups": [{"name": "s", "direction": "long"}]}
        inferences = _pop_direction_inferences(candidate)
        assert 0 in inferences
        assert inferences[0]["inferred"] is True
        assert inferences[0]["rationale"] == ""

    def test_missing_rationale_defaults_empty(self):
        candidate = {
            "setups": [{"name": "s", "direction": "long", "direction_inferred": True}]
        }
        inferences = _pop_direction_inferences(candidate)
        assert inferences[0]["rationale"] == ""

    def test_multiple_setups(self):
        candidate = {
            "setups": [
                {"name": "s1", "direction": "long",
                 "direction_inferred": True, "direction_rationale": "r1"},
                {"name": "s2", "direction": "short",
                 "direction_inferred": False, "direction_rationale": "r2"},
                {"name": "s3", "direction": "long"},  # no hints
            ]
        }
        inferences = _pop_direction_inferences(candidate)
        assert len(inferences) == 3
        assert inferences[0] == {"inferred": True, "rationale": "r1"}
        assert inferences[1] == {"inferred": False, "rationale": "r2"}
        assert inferences[2] == {"inferred": True, "rationale": ""}

    def test_inferred_falsy_values(self):
        """Empty string, 0, None are falsy → inferred=False (bool() coercion)."""
        for falsy in ["", 0, None]:
            candidate = {
                "setups": [{"name": "s", "direction": "long",
                            "direction_inferred": falsy}]
            }
            inferences = _pop_direction_inferences(candidate)
            assert inferences[0]["inferred"] is False, f"falsy {falsy!r} should yield False"

    def test_non_dict_candidate(self):
        assert _pop_direction_inferences("not a dict") == {}

    def test_non_list_setups(self):
        assert _pop_direction_inferences({"setups": "not a list"}) == {}

    def test_non_dict_setup(self):
        candidate = {"setups": ["string", 42, None]}
        assert _pop_direction_inferences(candidate) == {}

    def test_candidate_has_no_setups_key(self):
        assert _pop_direction_inferences({"other": "data"}) == {}

    def test_empty_setups_list(self):
        assert _pop_direction_inferences({"setups": []}) == {}

    def test_does_not_mutate_original_on_non_dict_setup(self):
        """When a setup is not a dict, the function skips it without error."""
        candidate = {"setups": [None, {"name": "s", "direction": "long",
                                        "direction_inferred": True}]}
        inferences = _pop_direction_inferences(candidate)
        assert 1 in inferences  # only the second setup was processed
        assert 0 not in inferences


# ============================================================================ #
# _build_setup_confirmations  —  pair validated setups with inference info     #
# ============================================================================ #

class TestBuildSetupConfirmations:

    def _spec_with_setups(self, directions: list[str]) -> StrategySpec:
        """Build a minimal StrategySpec with one setup per direction given."""
        return StrategySpec.model_validate({
            "schema_version": "1.0",
            "id": "test",
            "name": "test",
            "instrument": {"symbol": "EURUSD", "asset_class": "forex"},
            "timeframes": {"entry": "H1"},
            "setups": [
                {
                    "name": f"setup {i}",
                    "direction": d,
                    "entry": {
                        "operator": "all",
                        "children": [
                            {
                                "kind": "indicator",
                                "indicator": "rsi",
                                "params": {"period": 14},
                                "comparator": "lt",
                                "value": 30,
                            }
                        ],
                    },
                    "exit": {
                        "stop_loss": {"model": "atr", "value": 1.5},
                        "take_profit": [{"model": "rr", "value": 2.0, "close_percent": 100}],
                    },
                    "per_trade_risk": {"model": "fixed_percent", "value": 1.0},
                }
                for i, d in enumerate(directions)
            ],
            "risk": {
                "guards": {
                    "disallow_martingale": True,
                    "disallow_averaging_down": True,
                    "disallow_grid": True,
                }
            },
            "execution": {"mode": "semi_auto"},
            "version": 1,
            "metadata": {
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "author_user_id": "",
            },
        })

    def test_single_inferred_setup(self):
        spec = self._spec_with_setups(["long"])
        inferences = {0: {"inferred": True, "rationale": "RSI below 30"}}
        confirmations = _build_setup_confirmations(spec, inferences)
        assert len(confirmations) == 1
        assert confirmations[0]["index"] == 0
        assert confirmations[0]["direction"] == "long"
        assert confirmations[0]["inferred"] is True
        assert confirmations[0]["rationale"] == "RSI below 30"

    def test_single_explicit_setup(self):
        spec = self._spec_with_setups(["short"])
        inferences = {0: {"inferred": False, "rationale": ""}}
        confirmations = _build_setup_confirmations(spec, inferences)
        assert confirmations[0]["inferred"] is False

    def test_missing_inference_defaults_to_inferred(self):
        """When inference data is missing for a setup, default to inferred=True."""
        spec = self._spec_with_setups(["long"])
        confirmations = _build_setup_confirmations(spec, {})
        assert confirmations[0]["inferred"] is True
        assert confirmations[0]["rationale"] == ""

    def test_multiple_setups_mixed_inference(self):
        spec = self._spec_with_setups(["long", "short", "long"])
        inferences = {
            0: {"inferred": True, "rationale": "r1"},
            2: {"inferred": True, "rationale": "r3"},
            # index 1 missing intentionally
        }
        confirmations = _build_setup_confirmations(spec, inferences)
        assert len(confirmations) == 3
        assert confirmations[0] == {"index": 0, "name": "setup 0", "direction": "long",
                                     "inferred": True, "rationale": "r1"}
        assert confirmations[1] == {"index": 1, "name": "setup 1", "direction": "short",
                                     "inferred": True, "rationale": ""}
        assert confirmations[2] == {"index": 2, "name": "setup 2", "direction": "long",
                                     "inferred": True, "rationale": "r3"}

    def test_setup_names_are_included(self):
        spec = self._spec_with_setups(["long", "short"])
        confirmations = _build_setup_confirmations(spec, {})
        assert confirmations[0]["name"] == "setup 0"
        assert confirmations[1]["name"] == "setup 1"

    def test_inferred_defaults_to_true_when_key_missing_in_dict(self):
        """If inference dict has the index but missing 'inferred' key."""
        spec = self._spec_with_setups(["long"])
        confirmations = _build_setup_confirmations(spec, {0: {"rationale": "x"}})
        assert confirmations[0]["inferred"] is True

    def test_rationale_defaults_to_empty_when_key_missing(self):
        spec = self._spec_with_setups(["long"])
        confirmations = _build_setup_confirmations(spec, {0: {"inferred": False}})
        assert confirmations[0]["rationale"] == ""


# ============================================================================ #
# _format_validation_errors  —  format pydantic errors for the parse response  #
# ============================================================================ #

class TestFormatValidationErrors:

    def test_validation_error_on_empty_strategy(self):
        try:
            StrategySpec.model_validate({"schema_version": "1.0"})  # missing many fields
        except ValidationError as exc:
            errors = _format_validation_errors(exc)
            assert len(errors) >= 1
            # All error entries have the expected shape
            for e in errors:
                assert "field" in e
                assert "problem" in e
