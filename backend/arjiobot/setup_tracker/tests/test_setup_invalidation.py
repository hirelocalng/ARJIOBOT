"""Invalidation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arjiobot.fvg.fvg_models import FVGDirection, FairValueGap, build_fvg_id
from arjiobot.market_data.candle_models import Candle, Timeframe
from arjiobot.setup_tracker.setup_invalidation import (
    close_above_12m_fvg,
    high_sequence_invalidation_reason,
    retrace_window_passed,
    should_invalidate_retrace_window,
)
from arjiobot.setup_tracker.setup_models import InvalidationReason


def make_candle(index: int, *, high: str, low: str, close: str, timeframe_minutes: int = 8) -> Candle:
    timeframe = Timeframe(timeframe_minutes)
    return Candle(
        symbol="BTCUSDT",
        timeframe=timeframe,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index * timeframe_minutes),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def make_fvg() -> FairValueGap:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return FairValueGap(
        fvg_id=build_fvg_id(symbol="BTCUSDT", timeframe=Timeframe(12), direction=FVGDirection.BEARISH, c1_id="c1", c2_id="c2", c3_id="c3"),
        symbol="BTCUSDT",
        timeframe=Timeframe(12),
        direction=FVGDirection.BEARISH,
        timestamp=start + timedelta(minutes=12),
        confirmed_at=start + timedelta(minutes=36),
        c1_id="c1",
        c2_id="c2",
        c3_id="c3",
        c1_timestamp=start,
        c2_timestamp=start + timedelta(minutes=12),
        c3_timestamp=start + timedelta(minutes=24),
        upper_boundary=Decimal("96"),
        lower_boundary=Decimal("88"),
        gap_size=Decimal("8"),
        gap_size_percent=8.0,
    )


def test_retrace_window_pass_and_fail() -> None:
    fvg = make_fvg()
    passed, candle = retrace_window_passed(fvg, [make_candle(1, high="97", low="90", close="92")])
    assert passed
    assert candle is not None
    assert should_invalidate_retrace_window(
        fvg,
        [
            make_candle(1, high="87", low="80", close="84"),
            make_candle(2, high="87", low="80", close="84"),
            make_candle(3, high="87", low="80", close="84"),
            make_candle(4, high="87", low="80", close="84"),
        ],
    )


def test_close_above_12m_fvg_invalidation() -> None:
    assert close_above_12m_fvg(make_fvg(), make_candle(1, high="98", low="90", close="97", timeframe_minutes=1))


def test_third_high_invalidation_reason() -> None:
    reason = high_sequence_invalidation_reason(
        make_fvg(),
        [
            make_candle(1, high="90", low="88", close="89", timeframe_minutes=1),
            make_candle(2, high="92", low="89", close="91", timeframe_minutes=1),
            make_candle(3, high="94", low="90", close="92", timeframe_minutes=1),
        ],
    )
    assert reason is InvalidationReason.THIRD_HIGH_INSIDE_12M_FVG
