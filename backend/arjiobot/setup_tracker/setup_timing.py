"""Timing and reference calculations for Setup Tracker."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from arjiobot.fvg.fvg_models import FairValueGap
from arjiobot.market_data.candle_models import Candle, to_decimal


def calculate_target_references(
    *,
    fvg_16m: FairValueGap,
    candles_8m_after_16m: Sequence[Candle],
) -> tuple[Decimal, Decimal, Decimal]:
    """Return target A, target B, and final bearish target reference."""
    if fvg_16m.fvg_completion_candle_low is None:
        raise ValueError("16M FVG completion candle low is required")
    if len(candles_8m_after_16m) < 3:
        raise ValueError("three completed 8M candles are required")
    target_a = to_decimal(fvg_16m.fvg_completion_candle_low)
    target_b = min(candle.low for candle in candles_8m_after_16m[:3])
    return target_a, target_b, min(target_a, target_b)


def calculate_stop_reference(swing_16m_price) -> Decimal:
    """Return bearish stop reference from 16M swing high price."""
    return to_decimal(swing_16m_price)


def retrace_time_remaining(completed_8m_count: int) -> str:
    """Return a deterministic text time-remaining value for the 3-candle window."""
    remaining = max(0, 3 - completed_8m_count)
    return f"{remaining}x8M"
