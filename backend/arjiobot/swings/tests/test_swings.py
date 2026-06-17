"""Detector tests for the Swing Detection Engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe
from arjiobot.swings.swing_models import SwingStatus, SwingType
from arjiobot.swings.swings import SwingDetectionEngine, benchmark_detection, candle_id


def make_candle(
    index: int,
    *,
    high: int,
    low: int,
    symbol: str = "BTCUSDT",
    timeframe_minutes: int = 1,
    status: CandleStatus = CandleStatus.CLOSED,
) -> Candle:
    """Create a deterministic test candle."""
    timeframe = Timeframe(timeframe_minutes)
    timestamp = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(
        minutes=index * timeframe_minutes
    )
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=Decimal(low + 1),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high - 1),
        volume=Decimal("10"),
        status=status,
    )


def test_historical_scan_detects_highs_and_lows_in_one_pass() -> None:
    """Historical detection returns structured active swings."""
    candles = [
        make_candle(0, high=100, low=95),
        make_candle(1, high=110, low=94),
        make_candle(2, high=99, low=90),
        make_candle(3, high=98, low=93),
        make_candle(4, high=97, low=94),
    ]
    engine = SwingDetectionEngine()

    result = engine.detect_all_swings(candles)

    assert len(result.swing_highs) == 1
    assert len(result.swing_lows) == 1
    assert result.count == 2
    assert result.swing_highs[0].status is SwingStatus.ACTIVE
    assert result.swing_lows[0].status is SwingStatus.ACTIVE
    assert result.swing_highs[0].confirmed_at == candles[2].end_timestamp
    assert result.swing_lows[0].confirmed_at == candles[3].end_timestamp


def test_detector_consumes_only_closed_candles() -> None:
    """Open candles are rejected for both historical and live processing."""
    candles = [
        make_candle(0, high=100, low=90),
        make_candle(1, high=110, low=91),
        make_candle(2, high=105, low=92, status=CandleStatus.OPEN),
    ]
    engine = SwingDetectionEngine()

    with pytest.raises(ValueError, match="closed candles"):
        engine.detect_all_swings(candles)

    with pytest.raises(ValueError, match="closed candles"):
        engine.process_closed_candle(candles[2])


def test_false_positives_with_equal_values_are_rejected() -> None:
    """Strict greater-than and less-than rules reject equal high/low cases."""
    equal_highs = [
        make_candle(0, high=110, low=90),
        make_candle(1, high=110, low=91),
        make_candle(2, high=105, low=92),
    ]
    equal_lows = [
        make_candle(0, high=100, low=80),
        make_candle(1, high=99, low=80),
        make_candle(2, high=98, low=85),
    ]

    assert SwingDetectionEngine().detect_all_swings(equal_highs).count == 0
    assert SwingDetectionEngine().detect_all_swings(equal_lows).count == 0


def test_incremental_live_processing_confirms_only_after_c3_closes() -> None:
    """Live processing evaluates only the newly formed three-candle window."""
    candles = [
        make_candle(0, high=100, low=90),
        make_candle(1, high=110, low=91),
        make_candle(2, high=105, low=92),
    ]
    engine = SwingDetectionEngine()

    assert engine.process_closed_candle(candles[0]) == ()
    assert engine.process_closed_candle(candles[1]) == ()
    detected = engine.process_closed_candle(candles[2])

    assert len(detected) == 1
    assert detected[0].swing_type is SwingType.HIGH
    assert detected[0].timestamp == candles[1].timestamp
    assert detected[0].confirmed_at == candles[2].end_timestamp


def test_previous_swing_ids_are_populated() -> None:
    """New swings carry previous high and low IDs for the same symbol/timeframe."""
    candles = [
        make_candle(0, high=100, low=95),
        make_candle(1, high=110, low=96),
        make_candle(2, high=99, low=90),
        make_candle(3, high=108, low=94),
        make_candle(4, high=101, low=91),
        make_candle(5, high=109, low=95),
        make_candle(6, high=98, low=89),
    ]
    engine = SwingDetectionEngine()

    result = engine.detect_all_swings(candles)

    assert len(result.swing_highs) == 3
    assert len(result.swing_lows) == 2
    assert result.swing_highs[1].previous_swing_high_id == result.swing_highs[0].swing_id
    assert result.swing_highs[1].previous_swing_low_id == result.swing_lows[0].swing_id
    assert result.swing_lows[1].previous_swing_high_id == result.swing_highs[1].swing_id
    assert result.swing_lows[1].previous_swing_low_id == result.swing_lows[0].swing_id


def test_query_api_returns_structured_swings() -> None:
    """The stable query API exposes stored swing objects."""
    candles = [
        make_candle(0, high=100, low=95),
        make_candle(1, high=110, low=94),
        make_candle(2, high=99, low=90),
        make_candle(3, high=98, low=93),
    ]
    engine = SwingDetectionEngine()
    result = engine.detect_all_swings(candles)
    swing_high = result.swing_highs[0]

    assert engine.get_swing_by_id(swing_high.swing_id) == swing_high
    assert engine.get_latest_swing_high("BTCUSDT", "1M") == swing_high
    assert len(engine.get_active_swings(symbol="BTCUSDT", timeframe=1)) == 2
    assert engine.get_swings_for_timeframe("BTCUSDT", "1M", swing_type=SwingType.HIGH) == (
        swing_high,
    )
    assert len(
        engine.get_swings_between(
            "BTCUSDT",
            "1M",
            start=candles[0].timestamp,
            end=candles[-1].end_timestamp,
        )
    ) == 2


def test_source_candle_ids_are_deterministic() -> None:
    """Generated swings include stable replay-compatible source candle IDs."""
    candles = [
        make_candle(0, high=100, low=90),
        make_candle(1, high=110, low=91),
        make_candle(2, high=105, low=92),
    ]

    swing = SwingDetectionEngine().detect_all_swings(candles).swing_highs[0]

    assert swing.source_candle_ids == tuple(candle_id(candle) for candle in candles)


def test_strength_score_is_not_always_zero() -> None:
    """The initial scorer produces a bounded non-zero score."""
    candles = [
        make_candle(0, high=100, low=90),
        make_candle(1, high=120, low=91),
        make_candle(2, high=105, low=92),
    ]

    swing = SwingDetectionEngine().detect_all_swings(candles).swing_highs[0]

    assert 0.0 < swing.strength_score <= 100.0


def test_timeframe_agnostic_detection_supports_one_hour() -> None:
    """The detector does not hardcode timeframe values."""
    candles = [
        make_candle(0, high=100, low=90, timeframe_minutes=60),
        make_candle(1, high=110, low=91, timeframe_minutes=60),
        make_candle(2, high=105, low=92, timeframe_minutes=60),
    ]

    swing = SwingDetectionEngine().detect_all_swings(candles).swing_highs[0]

    assert swing.timeframe == Timeframe(60)


def test_benchmark_example_returns_metrics() -> None:
    """Benchmark helper provides validation metrics without extra strategy logic."""
    candles = [make_candle(index, high=100 + (index % 5), low=90 - (index % 3)) for index in range(20)]

    metrics = benchmark_detection(SwingDetectionEngine(), candles)

    assert metrics["candles"] == 20.0
    assert metrics["duration_ms"] >= 0.0
    assert metrics["candles_per_second"] >= 0.0
