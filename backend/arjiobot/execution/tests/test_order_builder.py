"""Order builder tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from arjiobot.execution.demo_execution import make_trade_plan
from arjiobot.execution.execution_models import OrderSide, OrderType
from arjiobot.execution.order_builder import build_order_instruction
from arjiobot.risk.risk_models import TradePlanStatus


def test_valid_bearish_market_sell_instruction() -> None:
    plan = make_trade_plan()
    instruction = build_order_instruction(plan)

    assert instruction.side is OrderSide.SELL
    assert instruction.order_type is OrderType.MARKET
    assert instruction.position_size == plan.position_size
    assert instruction.stop_loss_price == plan.stop_loss_price
    assert instruction.take_profit_price == plan.take_profit_price


def test_order_instruction_preserves_risk_engine_values_exactly() -> None:
    plan = make_trade_plan()
    instruction = build_order_instruction(plan)

    assert instruction.entry_reference_price == plan.entry_reference_price
    assert instruction.position_size == plan.position_size
    assert instruction.leverage == plan.leverage
    assert instruction.stop_loss_price == plan.stop_loss_price
    assert instruction.take_profit_price == plan.take_profit_price


def test_order_builder_rejects_non_approved_plan() -> None:
    plan = replace(make_trade_plan(), approval_status=TradePlanStatus.REJECTED)

    with pytest.raises(ValueError, match="not executable"):
        build_order_instruction(plan)
