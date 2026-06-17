"""Execution validation safeguards."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.execution.execution_models import ExecutionRejectionReason
from arjiobot.risk.risk_models import TradePlan, TradePlanStatus
from arjiobot.strategy.strategy_models import SignalAction


REQUIRED_TRADE_PLAN_FIELDS = (
    "trade_plan_id",
    "signal_id",
    "setup_id",
    "symbol",
    "direction",
    "action",
    "entry_reference_price",
    "stop_loss_price",
    "take_profit_price",
    "position_size",
    "leverage",
    "risk_amount",
    "fixed_risk_amount",
    "applied_margin_amount",
    "required_leverage",
    "max_allowed_leverage",
    "quantity",
    "expected_loss_at_sl",
    "rr_ratio",
)


def validate_trade_plan_for_execution(trade_plan: TradePlan) -> tuple[ExecutionRejectionReason, ...]:
    """Validate trade plan before instruction building."""
    reasons: list[ExecutionRejectionReason] = []
    if trade_plan.approval_status is not TradePlanStatus.APPROVED:
        reasons.append(ExecutionRejectionReason.TRADE_PLAN_NOT_APPROVED)
    if any(getattr(trade_plan, field_name) is None for field_name in REQUIRED_TRADE_PLAN_FIELDS):
        reasons.append(ExecutionRejectionReason.MISSING_REQUIRED_FIELD)
    if trade_plan.action is not SignalAction.MARKET_SELL_READY:
        reasons.append(ExecutionRejectionReason.UNSUPPORTED_ACTION)
    if trade_plan.position_size <= Decimal("0"):
        reasons.append(ExecutionRejectionReason.INVALID_POSITION_SIZE)
    if trade_plan.leverage < Decimal("1"):
        reasons.append(ExecutionRejectionReason.INVALID_LEVERAGE)
    if trade_plan.required_leverage <= Decimal("0") or trade_plan.leverage != trade_plan.required_leverage:
        reasons.append(ExecutionRejectionReason.INVALID_LEVERAGE)
    if trade_plan.required_leverage > trade_plan.max_allowed_leverage:
        reasons.append(ExecutionRejectionReason.INVALID_LEVERAGE)
    if trade_plan.trade_type != "ISOLATED_MARGIN" or trade_plan.margin_mode != "isolated":
        reasons.append(ExecutionRejectionReason.MISSING_REQUIRED_FIELD)
    if trade_plan.applied_margin_amount <= Decimal("0") or trade_plan.risk_amount != trade_plan.applied_margin_amount:
        reasons.append(ExecutionRejectionReason.MISSING_REQUIRED_FIELD)
    if trade_plan.expected_loss_at_sl <= Decimal("0") or abs(trade_plan.expected_loss_at_sl - trade_plan.risk_amount) > max(Decimal("0.00000001"), trade_plan.risk_amount * Decimal("0.000001")):
        reasons.append(ExecutionRejectionReason.INVALID_POSITION_SIZE)
    if trade_plan.stop_loss_price is None or trade_plan.entry_reference_price is None or trade_plan.stop_loss_price <= trade_plan.entry_reference_price:
        reasons.append(ExecutionRejectionReason.INVALID_STOP_LOSS)
    if trade_plan.take_profit_price is None or trade_plan.entry_reference_price is None or trade_plan.take_profit_price >= trade_plan.entry_reference_price:
        reasons.append(ExecutionRejectionReason.INVALID_TAKE_PROFIT)
    return tuple(dict.fromkeys(reasons))
