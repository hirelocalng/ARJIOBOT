"""Execution state tests."""

from __future__ import annotations

from datetime import timedelta

from arjiobot.execution.demo_execution import make_trade_plan
from arjiobot.execution.execution_models import ExecutionStatus
from arjiobot.execution.execution_engine import ExecutionEngine
from arjiobot.execution.order_state import transition_execution_status


def test_execution_lifecycle_transition() -> None:
    execution = ExecutionEngine().execute_trade_plan(make_trade_plan())
    cancelled = transition_execution_status(execution, ExecutionStatus.CANCELLED, execution.created_at + timedelta(minutes=1), "manual")

    assert cancelled.status is ExecutionStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert cancelled.metadata["status_reason"] == "manual"

