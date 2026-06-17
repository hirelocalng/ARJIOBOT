"""Demo, validation, and benchmark examples for the Swing Detection Engine.

Run from ``ArjioBot/backend``:

    python -m arjiobot.swings.demo_swings
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arjiobot.market_data.candle_models import Candle, Timeframe
from arjiobot.swings.swings import SwingDetectionEngine, benchmark_detection


def build_validation_dataset() -> list[Candle]:
    """Build candles with one swing high, one swing low, and rejected equals."""
    highs = [100, 110, 105, 101, 101, 99, 104, 102]
    lows = [95, 96, 90, 94, 94, 91, 89, 92]
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles: list[Candle] = []

    for index, (high, low) in enumerate(zip(highs, lows)):
        candles.append(
            Candle(
                symbol="BTCUSDT",
                timeframe=Timeframe(1),
                timestamp=start + timedelta(minutes=index),
                open=Decimal(low + 1),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(high - 1),
                volume=Decimal("10"),
            )
        )
    return candles


def build_benchmark_dataset(size: int = 5_000) -> list[Candle]:
    """Build deterministic candles for a lightweight benchmark example."""
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles: list[Candle] = []
    for index in range(size):
        wave = index % 9
        high = Decimal(100 + wave + (index % 3))
        low = Decimal(90 + wave - (index % 2))
        candles.append(
            Candle(
                symbol="BTCUSDT",
                timeframe=Timeframe(1),
                timestamp=start + timedelta(minutes=index),
                open=low + Decimal("1"),
                high=high,
                low=low,
                close=high - Decimal("1"),
                volume=Decimal("10"),
            )
        )
    return candles


def main() -> None:
    """Run validation and benchmark examples."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    engine = SwingDetectionEngine()
    result = engine.detect_all_swings(build_validation_dataset())

    print(f"swing highs: {len(result.swing_highs)}")
    print(f"swing lows: {len(result.swing_lows)}")
    for swing in result.all_swings:
        print(
            f"{swing.swing_type.value} {swing.symbol} {swing.timeframe.label} "
            f"timestamp={swing.timestamp.isoformat()} confirmed_at={swing.confirmed_at.isoformat()} "
            f"price={swing.price} strength={swing.strength_score:.2f}"
        )

    logging.getLogger("arjiobot.swings.swings").setLevel(logging.WARNING)
    metrics = benchmark_detection(SwingDetectionEngine(), build_benchmark_dataset())
    print(
        "benchmark "
        f"candles={metrics['candles']:.0f} swings={metrics['swings']:.0f} "
        f"duration_ms={metrics['duration_ms']:.2f} "
        f"candles_per_second={metrics['candles_per_second']:.2f}"
    )


if __name__ == "__main__":
    main()
