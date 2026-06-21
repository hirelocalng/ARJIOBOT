"""Invalidation logic for Setup Tracker."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Sequence

from arjiobot.fvg.fvg_models import FairValueGap
from arjiobot.fvg.fvg_tap_rules import candle_touches_fvg, evaluate_bearish_high_sequence, evaluate_bullish_low_sequence
from arjiobot.market_data.candle_models import Candle, ensure_utc
from arjiobot.setup_tracker.setup_models import InvalidationReason, Setup, SetupState, SetupStatus


def invalidate(
    setup: Setup,
    reason: InvalidationReason,
    invalidated_at: datetime,
) -> Setup:
    """Return an invalidated setup."""
    changed_at = ensure_utc(invalidated_at)
    return replace(
        setup,
        current_state=SetupState.INVALIDATED,
        status=SetupStatus.INVALIDATED,
        invalidated_at=changed_at,
        invalidation_reason=reason,
        updated_at=changed_at,
    )


def retrace_window_passed(fvg_12m: FairValueGap, candles_8m: Sequence[Candle]) -> tuple[bool, Candle | None]:
    """Return whether price retraced into 12M FVG within first three 8M candles."""
    for candle in candles_8m[:3]:
        if candle_touches_fvg(fvg_12m, candle):
            return True, candle
    return False, None


def should_invalidate_retrace_window(fvg_12m: FairValueGap, candles_8m: Sequence[Candle]) -> bool:
    """Return whether the retrace window expired."""
    passed, _ = retrace_window_passed(fvg_12m, candles_8m)
    return len(candles_8m) >= 3 and not passed


def close_above_12m_fvg(fvg_12m: FairValueGap, candle_1m: Candle) -> bool:
    """Return whether a 1M candle taps and closes above the 12M FVG."""
    return candle_touches_fvg(fvg_12m, candle_1m) and candle_1m.close > fvg_12m.upper_boundary


def close_below_12m_fvg(fvg_12m: FairValueGap, candle_1m: Candle) -> bool:
    """Return whether a 1M candle taps and closes below the 12M FVG (mirror of close_above_12m_fvg)."""
    return candle_touches_fvg(fvg_12m, candle_1m) and candle_1m.close < fvg_12m.lower_boundary


def high_sequence_invalidation_reason(
    fvg_12m: FairValueGap,
    candles_1m: Sequence[Candle],
) -> InvalidationReason | None:
    """Return high/consolidation invalidation reason, if any."""
    result = evaluate_bearish_high_sequence(fvg_12m, candles_1m)
    if result.state.value != "INVALID":
        return None
    if result.high_count >= 3:
        return InvalidationReason.THIRD_HIGH_INSIDE_12M_FVG
    return InvalidationReason.CLOSE_ABOVE_12M_FVG


def low_sequence_invalidation_reason(
    fvg_12m: FairValueGap,
    candles_1m: Sequence[Candle],
) -> InvalidationReason | None:
    """Return low/consolidation invalidation reason, if any (mirror of high_sequence_invalidation_reason)."""
    result = evaluate_bullish_low_sequence(fvg_12m, candles_1m)
    if result.state.value != "INVALID":
        return None
    if result.high_count >= 3:
        return InvalidationReason.THIRD_LOW_INSIDE_12M_FVG
    return InvalidationReason.CLOSE_BELOW_12M_FVG
