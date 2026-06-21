"""Tap-rule tests for the FVG Engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arjiobot.fvg.fvg_models import FVGDirection
from arjiobot.fvg.fvg_tap_rules import (
    TapValidationState,
    bearish_tap_close_is_valid,
    candle_touches_fvg,
    evaluate_bearish_12m_tap,
    evaluate_bearish_high_sequence,
    evaluate_bullish_low_sequence,
    fvg_inside_bearish_leg,
    fvg_inside_bullish_leg,
)
from arjiobot.fvg.tests.test_fvg_models import make_fvg
from arjiobot.market_data.candle_models import Candle, Timeframe


def make_candle(index: int, *, high: str, low: str, close: str) -> Candle:
    """Create a tap-rule candle."""
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(1),
        timestamp=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("10"),
    )


def test_generic_tap_rule_intersects_zone() -> None:
    """A candle touching the inclusive zone is tapped."""
    fvg = make_fvg()

    assert candle_touches_fvg(fvg, make_candle(0, high="91", low="89", close="90"))
    assert not candle_touches_fvg(fvg, make_candle(1, high="89", low="80", close="85"))


def test_first_tap_close_inside_and_below_are_valid() -> None:
    """Bearish first tap close inside or below remains valid."""
    fvg = make_fvg()

    assert bearish_tap_close_is_valid(fvg, make_candle(0, high="94", low="90", close="93"))
    assert bearish_tap_close_is_valid(fvg, make_candle(1, high="94", low="88", close="89"))
    assert evaluate_bearish_12m_tap(fvg, make_candle(2, high="94", low="90", close="93")).state is TapValidationState.VALID


def test_first_tap_close_above_invalidates() -> None:
    """Bearish first tap close above upper boundary invalidates."""
    fvg = make_fvg()

    result = evaluate_bearish_12m_tap(fvg, make_candle(0, high="97", low="92", close="96"))

    assert result.state is TapValidationState.INVALID


def test_second_high_rule_and_third_high_invalidation() -> None:
    """Two highs are allowed, third high invalidates as consolidation."""
    fvg = make_fvg()
    valid = evaluate_bearish_high_sequence(
        fvg,
        [
            make_candle(0, high="91", low="90", close="90"),
            make_candle(1, high="93", low="91", close="92"),
        ],
    )
    invalid = evaluate_bearish_high_sequence(
        fvg,
        [
            make_candle(0, high="91", low="90", close="90"),
            make_candle(1, high="93", low="91", close="92"),
            make_candle(2, high="94", low="92", close="93"),
        ],
    )

    assert valid.state is TapValidationState.VALID
    assert valid.high_count == 2
    assert invalid.state is TapValidationState.INVALID
    assert invalid.high_count == 3


def test_second_high_close_above_invalidates() -> None:
    """A second high candle closing above the FVG invalidates."""
    fvg = make_fvg()
    result = evaluate_bearish_high_sequence(
        fvg,
        [
            make_candle(0, high="91", low="90", close="90"),
            make_candle(1, high="96", low="91", close="96"),
        ],
    )

    assert result.state is TapValidationState.INVALID


def test_any_confirmation_candle_touching_and_closing_above_invalidates() -> None:
    """Any confirmation-phase candle that taps and closes above invalidates."""
    fvg = make_fvg()
    result = evaluate_bearish_high_sequence(
        fvg,
        [
            make_candle(0, high="94", low="90", close="92"),
            make_candle(1, high="96", low="91", close="96"),
        ],
    )

    assert result.state is TapValidationState.INVALID


def test_location_rule_for_bearish_leg() -> None:
    """12M/8M bearish FVG must sit inside the 16M leg."""
    assert fvg_inside_bearish_leg(
        fvg=make_fvg(),
        swing_high_price=Decimal("120"),
        completion_candle_low=Decimal("80"),
    )
    assert not fvg_inside_bearish_leg(
        fvg=make_fvg(),
        swing_high_price=Decimal("94"),
        completion_candle_low=Decimal("80"),
    )


def test_location_rule_for_bullish_leg() -> None:
    """12M/8M bullish FVG must sit inside the 16M leg (mirror of the bearish rule)."""
    bullish_fvg = make_fvg(direction=FVGDirection.BULLISH)
    assert fvg_inside_bullish_leg(
        fvg=bullish_fvg,
        swing_low_price=Decimal("80"),
        completion_candle_high=Decimal("120"),
    )
    assert not fvg_inside_bullish_leg(
        fvg=bullish_fvg,
        swing_low_price=Decimal("80"),
        completion_candle_high=Decimal("94"),
    )
    assert not fvg_inside_bullish_leg(
        fvg=make_fvg(),
        swing_low_price=Decimal("80"),
        completion_candle_high=Decimal("120"),
    )


def test_bullish_low_sequence_mirrors_bearish_high_sequence() -> None:
    """Two lows are allowed, third low invalidates as consolidation (mirror of high-sequence rule)."""
    fvg = make_fvg(direction=FVGDirection.BULLISH)
    valid = evaluate_bullish_low_sequence(
        fvg,
        [
            make_candle(0, high="91", low="90", close="91"),
            make_candle(1, high="93", low="89", close="93"),
        ],
    )
    invalid = evaluate_bullish_low_sequence(
        fvg,
        [
            make_candle(0, high="91", low="90", close="91"),
            make_candle(1, high="93", low="89", close="93"),
            make_candle(2, high="94", low="88", close="94"),
        ],
    )

    assert valid.state is TapValidationState.VALID
    assert valid.high_count == 2
    assert invalid.state is TapValidationState.INVALID
    assert invalid.high_count == 3
