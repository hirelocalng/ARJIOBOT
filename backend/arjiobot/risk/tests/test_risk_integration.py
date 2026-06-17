"""Risk integration/report tests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.risk.demo_risk import build_validation_report, default_context, make_signal
from arjiobot.risk.risk_service import RiskService


def test_backtester_and_execution_compatibility_fields() -> None:
    config, snapshot, state = default_context()
    signal = make_signal()
    plan = RiskService().create_trade_plan(signal, config, snapshot, state)

    assert plan.symbol == signal.symbol
    assert plan.action == signal.action
    assert plan.position_size > 0
    assert plan.leverage >= 1
    assert plan.entry_reference_price == signal.entry_reference_price
    assert plan.stop_loss_price == signal.stop_reference_price
    assert plan.take_profit_price != signal.final_target_price
    assert plan.take_profit_price == Decimal("45.0")


def test_report_generation() -> None:
    report = build_validation_report()
    html_path = report["html_path"]
    png_path = report["png_path"]
    assert html_path.exists()
    assert png_path.exists()
    assert "Risk Engine Validation Report" in html_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")
