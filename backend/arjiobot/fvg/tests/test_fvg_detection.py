"""Detection tests for the FVG Engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from arjiobot.fvg.fvg import FVGDetectionEngine, benchmark_fvg_detection
from arjiobot.fvg.fvg_models import FVGDirection
from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe


def make_candle(
    index: int,
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    timeframe_minutes: int = 1,
    status: CandleStatus = CandleStatus.CLOSED,
) -> Candle:
    """Create a deterministic candle."""
    timeframe = Timeframe(timeframe_minutes)
    return Candle(
        symbol="BTCUSDT",
        timeframe=timeframe,
        timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        + timedelta(minutes=index * timeframe_minutes),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("10"),
        status=status,
    )


def bearish_window() -> list[Candle]:
    """Return a strict bearish FVG window."""
    return [
        make_candle(0, open_="100", high="105", low="95", close="101"),
        make_candle(1, open_="102", high="112", low="98", close="108"),
        make_candle(2, open_="89", high="90", low="80", close="82"),
    ]


def bullish_window() -> list[Candle]:
    """Return a strict bullish FVG window."""
    return [
        make_candle(0, open_="80", high="85", low="75", close="82"),
        make_candle(1, open_="84", high="92", low="80", close="90"),
        make_candle(2, open_="96", high="105", low="96", close="102"),
    ]


def test_valid_bearish_fvg_detected() -> None:
    """Bearish FVG boundaries follow Low(C1) > High(C3)."""
    result = FVGDetectionEngine().detect_fvgs(bearish_window())

    assert result.count == 1
    fvg = result.fvgs[0]
    assert fvg.direction is FVGDirection.BEARISH
    assert fvg.upper_boundary == Decimal("95")
    assert fvg.lower_boundary == Decimal("90")
    assert fvg.gap_size == Decimal("5")


def test_valid_bullish_fvg_detected() -> None:
    """Bullish FVG boundaries follow High(C1) < Low(C3)."""
    result = FVGDetectionEngine().detect_fvgs(bullish_window())

    assert result.count == 1
    fvg = result.fvgs[0]
    assert fvg.direction is FVGDirection.BULLISH
    assert fvg.lower_boundary == Decimal("85")
    assert fvg.upper_boundary == Decimal("96")


def test_equality_boundaries_are_rejected() -> None:
    """Equality does not count as an FVG."""
    bearish_equal = [
        make_candle(0, open_="100", high="105", low="95", close="101"),
        make_candle(1, open_="102", high="112", low="98", close="108"),
        make_candle(2, open_="94", high="95", low="90", close="94"),
    ]
    bullish_equal = [
        make_candle(0, open_="80", high="85", low="75", close="82"),
        make_candle(1, open_="84", high="92", low="80", close="90"),
        make_candle(2, open_="86", high="96", low="85", close="94"),
    ]

    assert FVGDetectionEngine().detect_fvgs(bearish_equal).count == 0
    assert FVGDetectionEngine().detect_fvgs(bullish_equal).count == 0


def test_no_fvg_false_positive_rejected() -> None:
    """Overlapping candles are not FVGs."""
    candles = [
        make_candle(0, open_="100", high="105", low="95", close="101"),
        make_candle(1, open_="102", high="108", low="98", close="104"),
        make_candle(2, open_="103", high="106", low="94", close="100"),
    ]

    assert FVGDetectionEngine().detect_fvgs(candles).count == 0


def test_htf_fvg_detection_marks_htf_role() -> None:
    """30M and above are marked as HTF FVGs."""
    fvg = FVGDetectionEngine().detect_fvgs(
        [
            make_candle(0, open_="100", high="105", low="95", close="101", timeframe_minutes=30),
            make_candle(1, open_="102", high="112", low="98", close="108", timeframe_minutes=30),
            make_candle(2, open_="89", high="90", low="80", close="82", timeframe_minutes=30),
        ]
    ).fvgs[0]

    assert fvg.is_htf_fvg


def test_live_processing_detects_only_new_window() -> None:
    """Incremental processing emits after C3 closes."""
    engine = FVGDetectionEngine()
    candles = bearish_window()

    assert engine.process_closed_candle(candles[0]) == ()
    assert engine.process_closed_candle(candles[1]) == ()
    detected = engine.process_closed_candle(candles[2])

    assert len(detected) == 1
    assert detected[0].confirmed_at == candles[2].end_timestamp


def test_open_candles_are_rejected() -> None:
    """Incomplete candles are not processed."""
    with pytest.raises(ValueError, match="closed candles"):
        FVGDetectionEngine().process_closed_candle(
            make_candle(0, open_="1", high="2", low="1", close="2", status=CandleStatus.OPEN)
        )


def test_replay_consistency_uses_deterministic_ids() -> None:
    """Same candle sequence produces same FVG ID."""
    first = FVGDetectionEngine().detect_fvgs(bearish_window()).fvgs[0]
    second = FVGDetectionEngine().detect_fvgs(bearish_window()).fvgs[0]

    assert first.fvg_id == second.fvg_id


def test_benchmark_behavior_returns_metrics() -> None:
    """Benchmark helper returns throughput metrics."""
    candles = [
        make_candle(i, open_="100", high=str(110 + (i % 4)), low=str(90 - (i % 3)), close="100")
        for i in range(60)
    ]

    metrics = benchmark_fvg_detection(FVGDetectionEngine(), candles)

    assert metrics["candles"] == 60.0
    assert metrics["duration_ms"] >= 0.0
    assert metrics["candles_per_second"] >= 0.0
