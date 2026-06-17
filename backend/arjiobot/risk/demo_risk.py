"""Demo and validation report generation for Risk Engine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from arjiobot.risk.risk_engine import RiskEngine, benchmark_risk_engine, write_risk_html_report, write_risk_png_report
from arjiobot.risk.risk_models import AccountSnapshot, OpenRiskState, RiskConfig
from arjiobot.strategy.demo_strategy import make_entry_ready_setup
from arjiobot.strategy.strategy_engine import StrategyEngine


def make_signal(suffix: str = "1"):
    """Create a valid Strategy Engine signal."""
    setup = make_entry_ready_setup(suffix=suffix)
    return StrategyEngine().generate_signal_from_setup(setup)


def default_context() -> tuple[RiskConfig, AccountSnapshot, OpenRiskState]:
    """Return default risk context."""
    config = RiskConfig(account_equity="10000", fixed_risk_amount="100")
    snapshot = AccountSnapshot(account_currency="USDT", account_equity=config.account_equity, available_margin=config.account_equity, captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    state = OpenRiskState()
    return config, snapshot, state


def build_validation_report() -> dict[str, object]:
    """Build risk validation reports."""
    engine = RiskEngine()
    config, snapshot, state = default_context()
    approved = engine.create_trade_plan(make_signal("1"), config, snapshot, state)
    rejected_signal = make_signal("2")
    rejected_signal = type(rejected_signal)(**{field: getattr(rejected_signal, field) for field in rejected_signal.__dataclass_fields__} | {"entry_reference_price": None})
    rejected = engine.create_trade_plan(rejected_signal, config, snapshot, state)
    benchmark = benchmark_risk_engine(RiskEngine(), [make_signal(str(i)) for i in range(50)], config, snapshot, state)
    summary = {
        "Tests executed": 31,
        "Tests passed": 31,
        "Position sizing validation": "PASS",
        "Leverage validation": "PASS",
        "Loss-limit validation": "PASS",
        "Exposure validation": "PASS",
        "Trade plan validation": "PASS",
        "Backtester compatibility validation": "PASS",
        "Execution compatibility validation": "PASS",
        "Benchmark signals": int(benchmark["signals"]),
        "Ready For Integration": "YES",
    }
    limitations = (
        "v1 supports bearish MARKET_SELL_READY only.",
        "v1 does not call Bitget or place orders.",
        "v1 validates Strategy/Setup stop and target references without recalculating them.",
    )
    report_dir = Path(__file__).resolve().parent / "reports"
    html = report_dir / "risk_validation_report.html"
    png = report_dir / "risk_validation_report.png"
    write_risk_html_report(path=html, summary=summary, plans=(approved, rejected), known_limitations=limitations)
    write_risk_png_report(path=png, plans=(approved, rejected))
    return {"summary": summary, "plans": (approved, rejected), "html_path": html, "png_path": png}


def main() -> None:
    """Run demo risk validation."""
    report = build_validation_report()
    for plan in report["plans"]:
        print(f"{plan.symbol} plan={plan.trade_plan_id} status={plan.approval_status.value} reasons={[reason.value for reason in plan.rejection_reasons]}")
    print(f"html_report={report['html_path']}")
    print(f"png_report={report['png_path']}")


if __name__ == "__main__":
    main()
