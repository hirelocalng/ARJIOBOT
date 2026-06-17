"""Fill simulation tests."""

from __future__ import annotations

from arjiobot.execution.demo_execution import make_trade_plan
from arjiobot.execution.fills import simulate_paper_fill
from arjiobot.execution.order_builder import build_order_instruction
from arjiobot.execution.execution_models import ExecutionStatus


def test_paper_fill_at_entry_reference_price() -> None:
    plan = make_trade_plan()
    instruction = build_order_instruction(plan)
    fill = simulate_paper_fill(instruction)

    assert fill.status is ExecutionStatus.FILLED
    assert fill.fill_price == instruction.entry_reference_price
    assert fill.filled_size == instruction.position_size
    assert fill.paper_execution

