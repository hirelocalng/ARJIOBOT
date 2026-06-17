"""Execution payload uses backend-calculated RR TP."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.execution.order_builder import build_order_instruction
from arjiobot.risk.demo_risk import default_context, make_signal
from arjiobot.risk.risk_engine import RiskEngine


def test_live_trade_payload_uses_backend_calculated_tp() -> None:
    config, snapshot, state = default_context()
    plan = RiskEngine().create_trade_plan(make_signal(), config, snapshot, state)
    instruction = build_order_instruction(plan)

    assert plan.selected_rr_profile == "RR_1_5"
    assert plan.actual_rr == Decimal("1.5")
    assert plan.take_profit_price == Decimal("45.0")
    assert instruction.take_profit_price == plan.take_profit_price
    assert instruction.position_size == plan.position_size
