"""Risk engine service tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from arjiobot.risk.demo_risk import default_context, make_signal
from arjiobot.risk.risk_engine import RiskEngine, benchmark_risk_engine
from arjiobot.risk.risk_models import RiskRejectionReason, TradePlanStatus


def test_approved_and_rejected_trade_plan_creation() -> None:
    config, snapshot, state = default_context()
    engine = RiskEngine()
    signal = make_signal()
    approved = engine.create_trade_plan(signal, config, snapshot, state)
    rejected = engine.create_trade_plan(type(signal)(**{field: getattr(signal, field) for field in signal.__dataclass_fields__} | {"entry_reference_price": None}), config, snapshot, state)

    assert approved.approval_status is TradePlanStatus.APPROVED
    assert rejected.approval_status is TradePlanStatus.REJECTED
    assert RiskRejectionReason.MISSING_ENTRY_REFERENCE_PRICE in rejected.rejection_reasons
    assert approved.stop_loss_price == signal.stop_reference_price
    assert approved.take_profit_price == Decimal("45.0")
    assert approved.fixed_risk_amount == config.fixed_risk_amount
    assert approved.selected_rr_profile == "RR_1_5"
    assert approved.actual_rr == Decimal("1.5")


def test_query_apis_and_status_update() -> None:
    config, snapshot, state = default_context()
    engine = RiskEngine()
    plan = engine.create_trade_plan(make_signal(), config, snapshot, state)
    updated = engine.update_trade_plan_status(plan.trade_plan_id, TradePlanStatus.SENT_TO_EXECUTION, plan.created_at + timedelta(minutes=1), reason="handoff")

    assert engine.get_trade_plan_by_id(plan.trade_plan_id) == updated
    assert engine.get_trade_plan_by_signal_id(plan.signal_id) == updated
    assert updated.metadata["status_reason"] == "handoff"


def test_leg_target_research_trade_plan_uses_signal_target() -> None:
    config, snapshot, state = default_context()
    config = replace(config, selected_rr_profile="LEG_TARGET_RESEARCH")
    engine = RiskEngine()
    signal = make_signal()

    plan = engine.create_trade_plan(signal, config, snapshot, state)

    assert plan.approval_status is TradePlanStatus.APPROVED
    assert plan.selected_rr_profile == "LEG_TARGET_RESEARCH"
    assert plan.take_profit_price == signal.final_target_price
    assert plan.actual_rr == Decimal("0.6666666666666666666666666667")


def test_benchmark_behavior() -> None:
    config, snapshot, state = default_context()
    metrics = benchmark_risk_engine(RiskEngine(), [make_signal(str(i)) for i in range(10)], config, snapshot, state)
    assert metrics["signals"] == 10.0
    assert metrics["signals_per_second"] >= 0.0
