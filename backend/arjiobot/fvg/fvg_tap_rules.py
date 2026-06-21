"""Tap and strategy validation rules for FVGs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from arjiobot.market_data.candle_models import Candle
from arjiobot.fvg.fvg_models import FVGDirection, FairValueGap


class TapValidationState(str, Enum):
    """Tap validation outcomes."""

    VALID = "VALID"
    INVALID = "INVALID"
    WAITING = "WAITING"


@dataclass(frozen=True, slots=True)
class TapValidationResult:
    """Result for strategy tap checks."""

    state: TapValidationState
    reason: str
    high_count: int = 0


def candle_touches_fvg(fvg: FairValueGap, candle: Candle) -> bool:
    """Return whether a candle range intersects the FVG zone."""
    return candle.high >= fvg.lower_boundary and candle.low <= fvg.upper_boundary


def bearish_tap_close_is_valid(fvg: FairValueGap, candle: Candle) -> bool:
    """Return whether a bearish tap candle closes inside or below the FVG."""
    if fvg.direction is not FVGDirection.BEARISH:
        raise ValueError("bearish tap close rule requires a bearish FVG")
    return candle.close <= fvg.upper_boundary


def bearish_high_inside_fvg(fvg: FairValueGap, candle: Candle) -> bool:
    """Return whether a candle creates a high inside the bearish FVG zone."""
    if fvg.direction is not FVGDirection.BEARISH:
        raise ValueError("bearish high rule requires a bearish FVG")
    return fvg.lower_boundary <= candle.high <= fvg.upper_boundary


def evaluate_bearish_12m_tap(
    fvg: FairValueGap,
    tap_candle: Candle,
) -> TapValidationResult:
    """Evaluate the first bearish 12M FVG tap candle close."""
    if not candle_touches_fvg(fvg, tap_candle):
        return TapValidationResult(TapValidationState.WAITING, "candle did not tap FVG")
    if bearish_tap_close_is_valid(fvg, tap_candle):
        return TapValidationResult(TapValidationState.VALID, "tap close inside or below FVG", 1)
    return TapValidationResult(TapValidationState.INVALID, "tap candle closed above FVG", 1)


def evaluate_bearish_high_sequence(
    fvg: FairValueGap,
    candles: Sequence[Candle],
) -> TapValidationResult:
    """Evaluate second high and third-high consolidation rules."""
    high_count = 0
    previous_high = None
    for candle in candles:
        if not candle_touches_fvg(fvg, candle):
            continue
        if candle.close > fvg.upper_boundary:
            return TapValidationResult(
                TapValidationState.INVALID,
                "confirmation candle closed above FVG",
                high_count,
            )
        if previous_high is None or candle.high > previous_high:
            high_count += 1
            previous_high = candle.high
            if high_count >= 3:
                return TapValidationResult(
                    TapValidationState.INVALID,
                    "third high inside FVG invalidates setup",
                    high_count,
                )
    state = TapValidationState.VALID if high_count else TapValidationState.WAITING
    return TapValidationResult(state, "high sequence remains valid", high_count)


def fvg_inside_bearish_leg(
    *,
    fvg: FairValueGap,
    swing_high_price,
    completion_candle_low,
) -> bool:
    """Return whether a bearish 12M/8M FVG sits inside the approved 16M leg."""
    if fvg.direction is not FVGDirection.BEARISH:
        return False
    return fvg.upper_boundary <= swing_high_price and fvg.lower_boundary >= completion_candle_low


def fvg_inside_bullish_leg(
    *,
    fvg: FairValueGap,
    swing_low_price,
    completion_candle_high,
) -> bool:
    """Return whether a bullish 12M/8M FVG sits inside the approved 16M leg (mirror of fvg_inside_bearish_leg)."""
    if fvg.direction is not FVGDirection.BULLISH:
        return False
    return fvg.lower_boundary >= swing_low_price and fvg.upper_boundary <= completion_candle_high


def evaluate_bullish_low_sequence(
    fvg: FairValueGap,
    candles: Sequence[Candle],
) -> TapValidationResult:
    """Evaluate second low and third-low consolidation rules (mirror of evaluate_bearish_high_sequence)."""
    low_count = 0
    previous_low = None
    for candle in candles:
        if not candle_touches_fvg(fvg, candle):
            continue
        if candle.close < fvg.lower_boundary:
            return TapValidationResult(
                TapValidationState.INVALID,
                "confirmation candle closed below FVG",
                low_count,
            )
        if previous_low is None or candle.low < previous_low:
            low_count += 1
            previous_low = candle.low
            if low_count >= 3:
                return TapValidationResult(
                    TapValidationState.INVALID,
                    "third low inside FVG invalidates setup",
                    low_count,
                )
    state = TapValidationState.VALID if low_count else TapValidationState.WAITING
    return TapValidationResult(state, "low sequence remains valid", low_count)
