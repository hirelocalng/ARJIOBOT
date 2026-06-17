"""Fill simulation helpers."""

from __future__ import annotations

from datetime import datetime

from arjiobot.execution.execution_models import ExecutionRecord, ExecutionStatus, OrderInstruction, build_execution_id
from arjiobot.market_data.candle_models import ensure_utc


def simulate_paper_fill(order_instruction: OrderInstruction, filled_at: datetime | None = None) -> ExecutionRecord:
    """Create a deterministic paper fill at entry reference price."""
    timestamp = ensure_utc(filled_at or order_instruction.created_at)
    return ExecutionRecord(
        execution_id=build_execution_id(order_instruction.trade_plan_id, order_instruction.created_at),
        trade_plan_id=order_instruction.trade_plan_id,
        signal_id=order_instruction.signal_id,
        setup_id=order_instruction.setup_id,
        symbol=order_instruction.symbol,
        status=ExecutionStatus.FILLED,
        order_instruction_id=order_instruction.order_instruction_id,
        created_at=order_instruction.created_at,
        submitted_at=order_instruction.created_at,
        filled_at=timestamp,
        fill_price=order_instruction.entry_reference_price,
        filled_size=order_instruction.position_size,
        stop_loss_price=order_instruction.stop_loss_price,
        take_profit_price=order_instruction.take_profit_price,
        paper_execution=True,
        metadata={
            **order_instruction.metadata,
            "selected_fixed_risk_amount": str(order_instruction.risk_amount),
            "applied_margin_amount": str(order_instruction.margin_amount),
            "applied_leverage": str(order_instruction.leverage),
        },
    )
