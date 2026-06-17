"""Execution safeguard tests."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from arjiobot.execution.demo_execution import make_trade_plan
from arjiobot.execution.execution_models import ExecutionRejectionReason
from arjiobot.execution.safeguards import validate_trade_plan_for_execution
from arjiobot.risk.risk_models import TradePlanStatus
from arjiobot.strategy.strategy_models import SignalAction


def test_rejection_reasons_for_invalid_trade_plans() -> None:
    plan = make_trade_plan()

    assert validate_trade_plan_for_execution(plan) == ()
    assert ExecutionRejectionReason.TRADE_PLAN_NOT_APPROVED in validate_trade_plan_for_execution(replace(plan, approval_status=TradePlanStatus.REJECTED))
    assert ExecutionRejectionReason.INVALID_POSITION_SIZE in validate_trade_plan_for_execution(replace(plan, position_size=Decimal("0")))
    assert ExecutionRejectionReason.INVALID_LEVERAGE in validate_trade_plan_for_execution(replace(plan, leverage=Decimal("0")))
    assert ExecutionRejectionReason.INVALID_STOP_LOSS in validate_trade_plan_for_execution(replace(plan, stop_loss_price=Decimal("80")))
    assert ExecutionRejectionReason.INVALID_TAKE_PROFIT in validate_trade_plan_for_execution(replace(plan, take_profit_price=Decimal("100")))


def test_missing_required_field_rejected() -> None:
    plan = replace(make_trade_plan(), entry_reference_price=None)

    assert ExecutionRejectionReason.MISSING_REQUIRED_FIELD in validate_trade_plan_for_execution(plan)


def test_unsupported_action_rejected() -> None:
    plan = replace(make_trade_plan(), action=SignalAction.MARKET_BUY_READY)

    assert ExecutionRejectionReason.UNSUPPORTED_ACTION in validate_trade_plan_for_execution(plan)
