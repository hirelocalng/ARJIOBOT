"""Order instruction builder."""

from __future__ import annotations

from datetime import datetime

from arjiobot.execution.execution_models import OrderInstruction, OrderSide, OrderType, TimeInForce, build_order_instruction_id
from arjiobot.execution.safeguards import validate_trade_plan_for_execution
from arjiobot.market_data.candle_models import ensure_utc
from arjiobot.risk.risk_models import TradePlan


def build_order_instruction(trade_plan: TradePlan, created_at: datetime | None = None) -> OrderInstruction:
    """Build bearish v1 market-sell instruction from approved TradePlan."""
    if validate_trade_plan_for_execution(trade_plan):
        raise ValueError("trade plan is not executable")
    timestamp = ensure_utc(created_at or trade_plan.created_at)
    return OrderInstruction(
        order_instruction_id=build_order_instruction_id(trade_plan.trade_plan_id, timestamp),
        trade_plan_id=trade_plan.trade_plan_id,
        signal_id=trade_plan.signal_id,
        setup_id=trade_plan.setup_id,
        symbol=trade_plan.symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        position_size=trade_plan.position_size,
        leverage=trade_plan.leverage,
        entry_reference_price=trade_plan.entry_reference_price,
        stop_loss_price=trade_plan.stop_loss_price,
        take_profit_price=trade_plan.take_profit_price,
        trade_type=trade_plan.trade_type,
        margin_mode=trade_plan.margin_mode,
        margin_amount=trade_plan.applied_margin_amount,
        risk_amount=trade_plan.risk_amount,
        required_leverage=trade_plan.required_leverage,
        max_allowed_leverage=trade_plan.max_allowed_leverage,
        notional_position_size=trade_plan.notional_value,
        expected_loss_at_sl=trade_plan.expected_loss_at_sl,
        reduce_only=False,
        time_in_force=TimeInForce.IOC,
        created_at=timestamp,
        metadata={
            "trade_type": trade_plan.trade_type,
            "margin_mode": trade_plan.margin_mode,
            "applied_margin_amount": str(trade_plan.applied_margin_amount),
            "risk_amount": str(trade_plan.risk_amount),
            "price_risk_percent": str(trade_plan.price_risk_percent),
            "required_leverage": str(trade_plan.required_leverage),
            "applied_leverage": str(trade_plan.leverage),
            "max_allowed_leverage": str(trade_plan.max_allowed_leverage),
            "notional_position_size": str(trade_plan.notional_value),
            "quantity": str(trade_plan.quantity),
            "expected_loss_at_sl": str(trade_plan.expected_loss_at_sl),
        },
    )
