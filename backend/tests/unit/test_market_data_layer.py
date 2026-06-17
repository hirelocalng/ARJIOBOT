"""Unit tests for the market data layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from arjiobot.market_data.candle_aggregator import CandleAggregator
from arjiobot.market_data.candle_models import Candle, Timeframe, build_synthetic_candle
from arjiobot.market_data.candle_store import CandleStore
from arjiobot.market_data.synthetic_timeframes import (
    DEFAULT_SYNTHETIC_TIMEFRAMES,
    SyntheticTimeframeRegistry,
)


def make_candle(
    minute: int,
    *,
    symbol: str = "BTCUSDT",
    timeframe: int = 1,
    open_price: int = 100,
) -> Candle:
    """Create a deterministic test candle."""
    price = Decimal(open_price + minute)
    return Candle(
        symbol=symbol,
        timeframe=Timeframe(timeframe),
        timestamp=datetime(2026, 1, 1, 0, minute, tzinfo=timezone.utc),
        open=price,
        high=price + Decimal("2"),
        low=price - Decimal("1"),
        close=price + Decimal("1"),
        volume=Decimal("10"),
    )


def test_default_registry_contains_required_synthetic_timeframes() -> None:
    """The default registry supports the approved custom timeframes."""
    assert tuple(timeframe.label for timeframe in DEFAULT_SYNTHETIC_TIMEFRAMES) == (
        "8M",
        "12M",
        "16M",
    )


def test_registry_accepts_future_custom_timeframes() -> None:
    """Future whole-minute timeframe combinations can be registered."""
    registry = SyntheticTimeframeRegistry()

    registry.register("10M")
    registry.register(15)
    registry.register(Timeframe(20))

    assert registry.contains("10M")
    assert registry.contains("15M")
    assert registry.contains("20M")


def test_timeframe_uses_strict_midnight_based_alignment() -> None:
    """Synthetic bucket starts are aligned to exact timeframe boundaries."""
    timeframe = Timeframe(16)
    timestamp = datetime(2026, 1, 1, 0, 31, tzinfo=timezone.utc)

    assert timeframe.floor_timestamp(timestamp) == datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc)
    assert timeframe.is_aligned(datetime(2026, 1, 1, 0, 32, tzinfo=timezone.utc))
    assert not timeframe.is_aligned(timestamp)


def test_build_synthetic_candle_from_complete_one_minute_sequence() -> None:
    """Synthetic candles preserve first open, max high, min low, last close, and volume."""
    source = [make_candle(index) for index in range(8)]

    candle = build_synthetic_candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(8),
        candles=source,
    )

    assert candle.timeframe.label == "8M"
    assert candle.timestamp == source[0].timestamp
    assert candle.open == source[0].open
    assert candle.high == max(item.high for item in source)
    assert candle.low == min(item.low for item in source)
    assert candle.close == source[-1].close
    assert candle.volume == Decimal("80")
    assert candle.source_count == 8


def test_build_synthetic_candle_rejects_missing_source_minutes() -> None:
    """Synthetic candles require a complete consecutive sequence."""
    source = [make_candle(index) for index in range(8)]
    source.pop(4)

    with pytest.raises(ValueError, match="requires 8 one-minute candles"):
        build_synthetic_candle(symbol="BTCUSDT", timeframe=Timeframe(8), candles=source)


def test_build_synthetic_candle_rejects_unaligned_start() -> None:
    """Synthetic candle source windows must start on an exact bucket boundary."""
    source = [make_candle(index) for index in range(1, 9)]

    with pytest.raises(ValueError, match="not aligned"):
        build_synthetic_candle(symbol="BTCUSDT", timeframe=Timeframe(8), candles=source)


def test_candle_store_keeps_candles_ordered_and_replaces_duplicates() -> None:
    """The candle store orders by timestamp and upserts exact duplicates."""
    store = CandleStore()
    first = make_candle(1)
    replacement = make_candle(1, open_price=200)
    second = make_candle(2)

    store.upsert(second)
    store.upsert(first)
    store.upsert(replacement)

    candles = store.range(
        symbol="BTCUSDT",
        timeframe="1M",
        start=first.timestamp,
        end=second.timestamp + timedelta(minutes=1),
    )

    assert [candle.timestamp.minute for candle in candles] == [1, 2]
    assert candles[0].open == Decimal("201")
    assert store.count(symbol="BTCUSDT", timeframe="1M") == 2


def test_aggregator_generates_default_synthetic_timeframes() -> None:
    """The aggregator emits 8M, 12M, and 16M candles from 1-minute candles."""
    aggregator = CandleAggregator()

    generated = aggregator.ingest_many([make_candle(index) for index in range(16)])

    assert [candle.timeframe.label for candle in generated] == ["8M", "12M", "8M", "16M"]
    assert aggregator.store.count(symbol="BTCUSDT", timeframe="8M") == 2
    assert aggregator.store.count(symbol="BTCUSDT", timeframe="12M") == 1
    assert aggregator.store.count(symbol="BTCUSDT", timeframe="16M") == 1


def test_aggregator_supports_registered_future_timeframes() -> None:
    """The aggregator can emit custom future synthetic timeframes."""
    registry = SyntheticTimeframeRegistry()
    registry.register("10M")
    aggregator = CandleAggregator(registry=registry)

    generated = aggregator.ingest_many([make_candle(index) for index in range(10)])

    assert any(candle.timeframe.label == "10M" for candle in generated)
    assert aggregator.store.count(symbol="BTCUSDT", timeframe="10M") == 1


def test_aggregator_rejects_non_one_minute_source_candles() -> None:
    """Only closed 1-minute candles may enter synthetic aggregation."""
    aggregator = CandleAggregator()
    candle = make_candle(0, timeframe=8)

    with pytest.raises(ValueError, match="only accepts 1-minute"):
        aggregator.ingest(candle)
