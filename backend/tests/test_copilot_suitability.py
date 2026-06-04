"""Pure Co-Pilot suitability check.

A tight-stop low-timeframe (scalp) setup is unsuitable for Co-Pilot; a wide-stop
high-timeframe (swing) setup is suitable; and the latency / breaker-fraction
constants are honored.
"""
from app.contract.schemas import Setup
from app.engine.copilot_suitability import assess_copilot_suitability


def _setup(stop_model: str = "atr", stop_value: float = 1.0, atr_period=14) -> Setup:
    return Setup.model_validate(
        {
            "name": "t",
            "direction": "long",
            "entry": {
                "operator": "all",
                "children": [
                    {
                        "kind": "indicator",
                        "indicator": "rsi",
                        "params": {"period": 14},
                        "comparator": "crosses_below",
                        "value": 30,
                    }
                ],
            },
            "exit": {
                "stop_loss": {"model": stop_model, "value": stop_value, "atr_period": atr_period},
                "take_profit": [{"model": "rr", "value": 2.0, "close_percent": 100}],
            },
            "per_trade_risk": {"model": "fixed_percent", "value": 1.0},
        }
    )


def test_low_timeframe_tight_stop_is_unsuitable():
    result = assess_copilot_suitability(entry_timeframe="M1", setup=_setup("atr", 1.0))
    assert result.suitable is False
    assert "Full Auto" in result.reason


def test_high_timeframe_wide_stop_is_suitable():
    result = assess_copilot_suitability(entry_timeframe="H4", setup=_setup("atr", 2.0))
    assert result.suitable is True
    assert "Suitable for Co-Pilot" in result.reason


def test_latency_assumption_constant_is_honored():
    setup = _setup("atr", 1.0)  # M1 eta = 0.5 * 1.0 * 60 * 0.25 = 7.5s
    # Default 30s assumption -> the loop is too slow -> unsuitable.
    assert assess_copilot_suitability(entry_timeframe="M1", setup=setup).suitable is False
    # Drop the assumed latency below the estimate -> the SAME setup becomes suitable.
    fast = assess_copilot_suitability(entry_timeframe="M1", setup=setup, approval_latency_seconds=5.0)
    assert fast.suitable is True


def test_breaker_fraction_constant_is_honored():
    setup = _setup("atr", 1.0)
    tight = assess_copilot_suitability(entry_timeframe="M5", setup=setup, breaker_fraction=0.1)
    loose = assess_copilot_suitability(entry_timeframe="M5", setup=setup, breaker_fraction=0.9)
    # A larger fraction allows more slip before tripping -> more time -> more suitable.
    assert loose.estimated_seconds_to_breaker > tight.estimated_seconds_to_breaker


def test_fixed_pips_stop_supported_both_ways():
    # M1, 5-pip stop -> tight scalp -> unsuitable.
    assert assess_copilot_suitability(entry_timeframe="M1", setup=_setup("fixed_pips", 5.0, None)).suitable is False
    # D1, 50-pip stop -> wide swing -> suitable.
    assert assess_copilot_suitability(entry_timeframe="D1", setup=_setup("fixed_pips", 50.0, None)).suitable is True
