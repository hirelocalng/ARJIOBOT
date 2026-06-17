"""Detection and service tests for the Expansion Candle Engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe
from arjiobot.expansion.expansion import (
    ExpansionDetectionEngine,
    ExpansionDirection,
    benchmark_expansion_detection,
)
from arjiobot.swings.swing_models import SwingType
from arjiobot.swings.swings import SwingDetectionEngine


def make_candle(
    index: int,
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    status: CandleStatus = CandleStatus.CLOSED,
) -> Candle:
    """Create a deterministic candle."""
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(1),
        timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("10"),
        status=status,
    )


def bearish_expansion_candles() -> list[Candle]:
    """Return candles forming a swing high with bearish expansion C3."""
    return [
        make_candle(0, open_="100", high="105", low="95", close="101"),
        make_candle(1, open_="102", high="112", low="98", close="108"),
        make_candle(2, open_="109", high="111", low="76", close="90"),
    ]


def bullish_expansion_candles() -> list[Candle]:
    """Return candles forming a swing low with bullish expansion C3."""
    return [
        make_candle(0, open_="90", high="100", low="85", close="88"),
        make_candle(1, open_="88", high="95", low="70", close="72"),
        make_candle(2, open_="72", high="133", low="71", close="120"),
    ]


def test_historical_scan_detects_bearish_expansion_from_swing_high() -> None:
    """Historical detection consumes confirmed swings, not raw rescans."""
    swing = SwingDetectionEngine().detect_all_swings(bearish_expansion_candles()).swing_highs[0]
    engine = ExpansionDetectionEngine(fvg_candidate_threshold=50.0)

    result = engine.detect_expansions((swing,))

    assert result.count == 1
    expansion = result.expansions[0]
    assert expansion.direction is ExpansionDirection.BEARISH
    assert expansion.swing_id == swing.swing_id
    assert expansion.swing_type is SwingType.HIGH
    assert expansion.expansion_ratio == pytest.approx(2.9166, rel=0.01)
    assert expansion.displacement_distance == Decimal("8")
    assert expansion.is_fvg_candidate


def test_historical_scan_detects_bullish_expansion_from_swing_low() -> None:
    """Swing lows create bullish expansions."""
    swing = SwingDetectionEngine().detect_all_swings(bullish_expansion_candles()).swing_lows[0]
    engine = ExpansionDetectionEngine(fvg_candidate_threshold=50.0)

    expansion = engine.detect_expansions((swing,)).expansions[0]

    assert expansion.direction is ExpansionDirection.BULLISH
    assert expansion.displacement_distance == Decimal("25")
    assert expansion.swing_type is SwingType.LOW


def test_size_only_false_positive_is_rejected() -> None:
    """A large C3 that does not close directionally beyond C2 is rejected."""
    candles = [
        make_candle(0, open_="100", high="105", low="95", close="101"),
        make_candle(1, open_="102", high="112", low="98", close="108"),
        make_candle(2, open_="109", high="111", low="76", close="100"),
    ]
    swing = SwingDetectionEngine().detect_all_swings(candles).swing_highs[0]

    result = ExpansionDetectionEngine().detect_expansions((swing,))

    assert result.count == 0
    assert result.rejected_count == 1


def test_ratio_false_negative_boundary_is_inclusive() -> None:
    """Ratios exactly at 2x and 4x are accepted when displacement exists."""
    candles = [
        make_candle(0, open_="100", high="105", low="95", close="101"),
        make_candle(1, open_="102", high="112", low="98", close="108"),
        make_candle(2, open_="109", high="111", low="87", close="94"),
    ]
    swing = SwingDetectionEngine().detect_all_swings(candles).swing_highs[0]

    result = ExpansionDetectionEngine().detect_expansions((swing,))

    assert result.count == 1
    assert result.expansions[0].expansion_ratio == pytest.approx(2.0)


def test_live_processing_uses_only_newly_confirmed_swings() -> None:
    """Live detection evaluates the newly closed C3 handoff only."""
    candles = bearish_expansion_candles()
    swing_engine = SwingDetectionEngine()
    expansion_engine = ExpansionDetectionEngine()

    assert expansion_engine.process_closed_candle(candles[0], swing_engine.process_closed_candle(candles[0])) == ()
    assert expansion_engine.process_closed_candle(candles[1], swing_engine.process_closed_candle(candles[1])) == ()
    swings = swing_engine.process_closed_candle(candles[2])
    expansions = expansion_engine.process_closed_candle(candles[2], swings)

    assert len(expansions) == 1
    assert expansions[0] == expansion_engine.get_latest_expansion("BTCUSDT", "1M")


def test_query_api_returns_structured_expansions() -> None:
    """The stable query API exposes stored expansion objects."""
    swing = SwingDetectionEngine().detect_all_swings(bearish_expansion_candles()).swing_highs[0]
    engine = ExpansionDetectionEngine(fvg_candidate_threshold=50.0)
    expansion = engine.detect_expansions((swing,)).expansions[0]

    assert engine.get_expansion_by_id(expansion.expansion_id) == expansion
    assert engine.get_latest_expansion("BTCUSDT", 1) == expansion
    assert engine.get_expansions_for_timeframe("BTCUSDT", "1M") == (expansion,)
    assert engine.get_fvg_candidates("BTCUSDT", "1M") == (expansion,)
    assert engine.get_expansions_between(
        "BTCUSDT",
        "1M",
        start=expansion.timestamp - timedelta(minutes=1),
        end=expansion.timestamp + timedelta(minutes=1),
    ) == (expansion,)


def test_open_candles_are_rejected_for_live_processing() -> None:
    """Live processing consumes only closed candles."""
    candle = make_candle(0, open_="1", high="2", low="1", close="2", status=CandleStatus.OPEN)

    with pytest.raises(ValueError, match="closed candles"):
        ExpansionDetectionEngine().process_closed_candle(candle)


def test_benchmark_returns_metrics() -> None:
    """Benchmark helper returns validation metrics."""
    swing = SwingDetectionEngine().detect_all_swings(bearish_expansion_candles()).swing_highs[0]

    metrics = benchmark_expansion_detection(ExpansionDetectionEngine(), (swing,) * 20)

    assert metrics["swings"] == 20.0
    assert metrics["duration_ms"] >= 0.0
    assert metrics["swings_per_second"] >= 0.0
