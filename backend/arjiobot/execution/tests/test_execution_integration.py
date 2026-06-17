"""Execution integration/report tests."""

from __future__ import annotations

from arjiobot.execution.demo_execution import build_validation_report, make_trade_plan
from arjiobot.execution.execution_engine import ExecutionEngine, benchmark_execution_engine


def test_backtester_compatibility_execution_record_fields() -> None:
    execution = ExecutionEngine().execute_trade_plan(make_trade_plan())

    assert execution.paper_execution
    assert execution.fill_price is not None
    assert execution.stop_loss_price is not None
    assert execution.take_profit_price is not None


def test_benchmark_behavior() -> None:
    metrics = benchmark_execution_engine(ExecutionEngine(), [make_trade_plan(str(index)) for index in range(10)])
    assert metrics["trade_plans"] == 10.0
    assert metrics["plans_per_second"] >= 0.0


def test_report_generation() -> None:
    report = build_validation_report()
    html_path = report["html_path"]
    png_path = report["png_path"]
    assert html_path.exists()
    assert png_path.exists()
    assert "Execution Engine Validation Report" in html_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")

