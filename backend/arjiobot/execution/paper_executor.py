"""Paper execution engine."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Protocol

from arjiobot.execution.execution_models import (
    ExecutionRecord,
    ExecutionStatus,
    OrderInstruction,
    OrderSide,
    OrderType,
    ProtectiveOrderPlan,
    build_protective_order_id,
)
from arjiobot.execution.fills import simulate_paper_fill
from arjiobot.market_data.candle_models import ensure_utc


class ExchangeExecutionAdapter(Protocol):
    """Future live exchange adapter boundary."""

    def set_leverage(self, *args, **kwargs): ...
    def place_market_order(self, *args, **kwargs): ...
    def place_stop_loss(self, *args, **kwargs): ...
    def place_take_profit(self, *args, **kwargs): ...
    def cancel_order(self, *args, **kwargs): ...
    def fetch_order_status(self, *args, **kwargs): ...


def plan_protective_orders(execution: ExecutionRecord) -> tuple[ProtectiveOrderPlan, ProtectiveOrderPlan]:
    """Create planned stop loss and take profit orders for bearish v1."""
    if execution.fill_price is None or execution.filled_size is None:
        raise ValueError("filled execution is required")
    created_at = execution.filled_at or execution.created_at
    stop = ProtectiveOrderPlan(
        protective_order_id=build_protective_order_id(execution.execution_id, OrderType.STOP),
        execution_id=execution.execution_id,
        trade_plan_id=execution.trade_plan_id,
        symbol=execution.symbol,
        side=OrderSide.BUY,
        order_type=OrderType.STOP,
        trigger_price=execution.stop_loss_price,
        position_size=execution.filled_size,
        reduce_only=True,
        created_at=created_at,
    )
    target = ProtectiveOrderPlan(
        protective_order_id=build_protective_order_id(execution.execution_id, OrderType.TAKE_PROFIT),
        execution_id=execution.execution_id,
        trade_plan_id=execution.trade_plan_id,
        symbol=execution.symbol,
        side=OrderSide.BUY,
        order_type=OrderType.TAKE_PROFIT,
        trigger_price=execution.take_profit_price,
        position_size=execution.filled_size,
        reduce_only=True,
        created_at=created_at,
    )
    return stop, target


def paper_execute(order_instruction: OrderInstruction, filled_at: datetime | None = None) -> ExecutionRecord:
    """Run full v1 paper lifecycle and plan protective orders."""
    filled = simulate_paper_fill(order_instruction, filled_at)
    protective = plan_protective_orders(filled)
    return replace(
        filled,
        status=ExecutionStatus.PROTECTIVE_ORDERS_PLANNED,
        protective_orders=protective,
        filled_at=ensure_utc(filled.filled_at or filled.created_at),
    )
