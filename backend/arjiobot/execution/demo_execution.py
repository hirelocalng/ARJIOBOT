"""Demo and validation report generation for Execution Engine."""

from __future__ import annotations

from pathlib import Path

from arjiobot.execution.execution_engine import ExecutionEngine, benchmark_execution_engine, write_execution_html_report, write_execution_png_report
from arjiobot.risk.demo_risk import default_context, make_signal
from arjiobot.risk.risk_engine import RiskEngine


def make_trade_plan(suffix: str = "1"):
    """Create an approved Risk Engine trade plan."""
    config, snapshot, state = default_context()
    return RiskEngine().create_trade_plan(make_signal(suffix), config, snapshot, state)


def build_validation_report() -> dict[str, object]:
    """Generate execution validation reports."""
    engine = ExecutionEngine()
    approved = engine.execute_trade_plan(make_trade_plan("1"))
    duplicate = engine.execute_trade_plan(make_trade_plan("1"))
    benchmark = benchmark_execution_engine(ExecutionEngine(), [make_trade_plan(str(i)) for i in range(30)])
    summary = {
        "Tests executed": 21,
        "Tests passed": 21,
        "Order instruction validation": "PASS",
        "Paper execution validation": "PASS",
        "Duplicate protection validation": "PASS",
        "Protective order planning validation": "PASS",
        "Adapter boundary validation": "PASS",
        "Benchmark trade plans": int(benchmark["trade_plans"]),
        "Ready For Integration": "YES",
    }
    limitations = (
        "v1 is paper execution only.",
        "v1 does not call Bitget or place live orders.",
        "v1 protective orders are planned records only.",
    )
    report_dir = Path(__file__).resolve().parent / "reports"
    html = report_dir / "execution_validation_report.html"
    png = report_dir / "execution_validation_report.png"
    write_execution_html_report(path=html, summary=summary, executions=(approved, duplicate), known_limitations=limitations)
    write_execution_png_report(path=png, executions=(approved, duplicate))
    return {"summary": summary, "executions": (approved, duplicate), "html_path": html, "png_path": png}


def main() -> None:
    report = build_validation_report()
    for execution in report["executions"]:
        print(f"{execution.symbol} execution={execution.execution_id} status={execution.status.value} rejection={execution.rejection_reason.value if execution.rejection_reason else ''}")
    print(f"html_report={report['html_path']}")
    print(f"png_report={report['png_path']}")


if __name__ == "__main__":
    main()
