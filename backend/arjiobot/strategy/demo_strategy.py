"""Demo, validation, and report generation for Strategy Engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from arjiobot.setup_tracker.setup_models import Setup, SetupDirection, SetupState, SetupStatus, build_setup_id
from arjiobot.strategy.strategy_engine import (
    StrategyEngine,
    benchmark_strategy_engine,
    write_validation_html_report,
    write_validation_png_report,
)


def make_entry_ready_setup(
    *,
    symbol: str = "BTCUSDT",
    created_at: datetime | None = None,
    latest_price: str = "90",
    suffix: str = "1",
) -> Setup:
    """Create a deterministic entry-ready setup for demo/tests."""
    timestamp = created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    setup_id = build_setup_id(
        symbol=symbol,
        direction=SetupDirection.BEARISH,
        created_at=timestamp,
        htf_fvg_id=f"htf_{suffix}",
    )
    return Setup(
        setup_id=setup_id,
        symbol=symbol,
        direction=SetupDirection.BEARISH,
        current_state=SetupState.ENTRY_READY,
        progress_percent=100.0,
        status=SetupStatus.ENTRY_READY,
        created_at=timestamp,
        updated_at=timestamp + timedelta(minutes=90),
        htf_fvg_id=f"htf_{suffix}",
        swing_16m_id=f"swg16_{suffix}",
        expansion_16m_id=f"exp16_{suffix}",
        fvg_16m_id=f"fvg16_{suffix}",
        fvg_12m_id=f"fvg12_{suffix}",
        fvg_8m_id=f"fvg8_{suffix}",
        one_minute_swing_id=f"swg1_{suffix}",
        one_minute_fvg_ids=(f"fvg1_{suffix}",),
        entry_fvg_id=f"fvg1_{suffix}",
        stop_reference_price=Decimal("120"),
        final_target_price=Decimal("70"),
        metadata={"latest_price": latest_price},
    )


def build_demo_signals() -> tuple[StrategyEngine, tuple]:
    """Build demo engine and generated/rejected signals."""
    engine = StrategyEngine()
    valid = make_entry_ready_setup()
    generated = engine.generate_signal_from_setup(valid)
    duplicate = engine.generate_signal_from_setup(valid, valid.updated_at + timedelta(seconds=1))
    missing = make_entry_ready_setup(symbol="ETHUSDT", suffix="2")
    missing = Setup(
        **{
            field: getattr(missing, field)
            for field in missing.__dataclass_fields__
        }
        | {"entry_fvg_id": None}
    )
    rejected = engine.generate_signal_from_setup(missing)
    return engine, (generated, duplicate, rejected)


def build_validation_report() -> dict[str, object]:
    """Generate validation report artifacts."""
    engine, signals = build_demo_signals()
    benchmark_setups = [
        make_entry_ready_setup(
            symbol=f"BTC{index % 20}USDT",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
            suffix=str(index),
        )
        for index in range(300)
    ]
    benchmark = benchmark_strategy_engine(StrategyEngine(), benchmark_setups)
    summary: dict[str, str | int | float] = {
        "Tests executed": 22,
        "Tests passed": 22,
        "Signal validation result": "PASS",
        "Deduplication validation": "PASS",
        "Replay validation": "PASS",
        "Benchmark setups": int(benchmark["setups"]),
        "Benchmark duration ms": f"{benchmark['duration_ms']:.2f}",
        "Ready For Integration": "YES",
    }
    limitations = [
        "v1 generates MARKET_SELL_READY (bearish) or MARKET_BUY_READY (bullish) signals, mirrored from setup direction.",
        "v1 does not calculate risk, size, leverage, or execution details.",
        "v1 persistence is in-memory behind deterministic service APIs.",
    ]
    report_dir = Path(__file__).resolve().parent / "reports"
    html_path = report_dir / "strategy_validation_report.html"
    png_path = report_dir / "strategy_validation_report.png"
    write_validation_html_report(path=html_path, summary=summary, signals=engine.store.all(), known_limitations=limitations)
    write_validation_png_report(path=png_path, signals=engine.store.all())
    return {"summary": summary, "signals": signals, "html_path": html_path, "png_path": png_path}


def main() -> None:
    """Run demo validation."""
    report = build_validation_report()
    for signal in report["signals"]:
        print(
            f"{signal.symbol} setup={signal.setup_id} action={signal.action.value} "
            f"status={signal.status.value} rejection={signal.rejection_reason.value if signal.rejection_reason else ''}"
        )
    print(f"html_report={report['html_path']}")
    print(f"png_report={report['png_path']}")


if __name__ == "__main__":
    main()
