"""Execution model tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from arjiobot.execution.execution_models import (
    ExecutionRecord,
    ExecutionRejectionReason,
    ExecutionStatus,
    OrderInstruction,
    OrderSide,
    OrderType,
    TimeInForce,
    build_execution_id,
    build_order_instruction_id,
    execution_to_record,
)


def make_instruction() -> OrderInstruction:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return OrderInstruction(
        order_instruction_id=build_order_instruction_id("tpl", created_at),
        trade_plan_id="tpl",
        signal_id="sig",
        setup_id="set",
        symbol="btcusdt",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        position_size=Decimal("1"),
        leverage=Decimal("3"),
        entry_reference_price=Decimal("90"),
        stop_loss_price=Decimal("120"),
        take_profit_price=Decimal("70"),
        trade_type="ISOLATED_MARGIN",
        margin_mode="isolated",
        margin_amount=Decimal("30"),
        risk_amount=Decimal("30"),
        required_leverage=Decimal("3"),
        max_allowed_leverage=Decimal("10"),
        notional_position_size=Decimal("90"),
        expected_loss_at_sl=Decimal("30"),
        reduce_only=False,
        time_in_force=TimeInForce.IOC,
        created_at=created_at,
    )


def test_order_instruction_and_execution_record_creation() -> None:
    instruction = make_instruction()
    execution = ExecutionRecord(
        execution_id=build_execution_id("tpl", instruction.created_at),
        trade_plan_id="tpl",
        signal_id="sig",
        setup_id="set",
        symbol="btcusdt",
        status=ExecutionStatus.REJECTED,
        order_instruction_id=None,
        created_at=instruction.created_at,
        rejected_at=instruction.created_at,
        rejection_reason=ExecutionRejectionReason.TRADE_PLAN_NOT_APPROVED,
    )
    record = execution_to_record(execution)

    assert instruction.symbol == "BTCUSDT"
    assert execution.symbol == "BTCUSDT"
    assert record["rejection_reason"] == "TRADE_PLAN_NOT_APPROVED"


def test_rejected_execution_requires_reason() -> None:
    with pytest.raises(ValueError, match="rejection_reason"):
        ExecutionRecord(
            execution_id="exe",
            trade_plan_id="tpl",
            signal_id="sig",
            setup_id="set",
            symbol="BTCUSDT",
            status=ExecutionStatus.REJECTED,
            order_instruction_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_execution_ids_are_deterministic() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert build_order_instruction_id("tpl", created_at) == build_order_instruction_id("tpl", created_at)
    assert build_execution_id("tpl", created_at) == build_execution_id("tpl", created_at)
