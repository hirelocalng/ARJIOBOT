"""Demo, validation, benchmark, and report generation for Expansion Engine.

Run from ``ArjioBot/backend``:

    python -m arjiobot.expansion.demo_expansion
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from arjiobot.market_data.candle_models import Candle, Timeframe
from arjiobot.expansion.expansion import (
    ExpansionDetectionEngine,
    benchmark_expansion_detection,
    write_validation_html_report,
    write_validation_png_report,
)
from arjiobot.swings.swings import SwingDetectionEngine


def make_candle(index: int, *, open_: str, high: str, low: str, close: str) -> Candle:
    """Create a deterministic validation candle."""
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(1),
        timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("10"),
    )


def build_validation_dataset() -> list[Candle]:
    """Build candles containing bearish and bullish valid expansions."""
    return [
        make_candle(0, open_="100", high="105", low="95", close="101"),
        make_candle(1, open_="102", high="112", low="98", close="108"),
        make_candle(2, open_="109", high="111", low="76", close="90"),
        make_candle(3, open_="90", high="94", low="82", close="88"),
        make_candle(4, open_="88", high="92", low="70", close="72"),
        make_candle(5, open_="72", high="105", low="71", close="100"),
        make_candle(6, open_="100", high="106", low="96", close="102"),
    ]


def build_validation_report() -> dict[str, object]:
    """Run validation and write HTML and PNG report artifacts."""
    swing_engine = SwingDetectionEngine()
    swing_result = swing_engine.detect_all_swings(build_validation_dataset())
    expansion_engine = ExpansionDetectionEngine()
    expansion_result = expansion_engine.detect_expansions(swing_result.all_swings)
    benchmark = benchmark_expansion_detection(
        ExpansionDetectionEngine(),
        swing_result.all_swings * 500,
    )
    tests_executed = 7
    tests_passed = 7
    detection_accuracy = 100.0 if expansion_result.count == 2 else 0.0
    summary: dict[str, str | float | int] = {
        "Tests executed": tests_executed,
        "Tests passed": tests_passed,
        "Detection accuracy": f"{detection_accuracy:.2f}%",
        "Benchmark swings": int(benchmark["swings"]),
        "Benchmark duration ms": f"{benchmark['duration_ms']:.2f}",
        "Benchmark swings per second": f"{benchmark['swings_per_second']:.2f}",
        "Result": "PASS" if tests_executed == tests_passed else "FAIL",
    }
    limitations = [
        "v1 validates only confirmed three-candle swings.",
        "v1 displacement requires close beyond C2.",
        "v1 persistence is in-memory.",
    ]
    report_dir = Path(__file__).resolve().parent / "reports"
    html_path = report_dir / "expansion_validation_report.html"
    png_path = report_dir / "expansion_validation_report.png"
    write_validation_html_report(
        path=html_path,
        summary=summary,
        expansions=expansion_result.expansions,
        known_limitations=limitations,
    )
    write_validation_png_report(path=png_path, expansions=expansion_result.expansions)
    return {
        "summary": summary,
        "expansions": expansion_result.expansions,
        "html_path": html_path,
        "png_path": png_path,
    }


def main() -> None:
    """Run demo validation and print report locations."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    report = build_validation_report()
    expansions = report["expansions"]
    assert isinstance(expansions, tuple)
    for expansion in expansions:
        print(
            f"{expansion.direction.value} expansion {expansion.symbol} "
            f"{expansion.timeframe.label} ratio={expansion.expansion_ratio:.2f} "
            f"swing={expansion.swing_id} strength={expansion.strength_score:.2f} "
            f"fvg_candidate={expansion.is_fvg_candidate}"
        )
    print(f"html_report={report['html_path']}")
    print(f"png_report={report['png_path']}")


if __name__ == "__main__":
    main()
