"""Execution service tests."""

from __future__ import annotations

from datetime import timedelta

from arjiobot.execution.demo_execution import make_trade_plan
from arjiobot.execution.execution_models import ExecutionRejectionReason, ExecutionStatus
from arjiobot.execution.execution_service import ExecutionService


def test_execute_trade_plan_and_queries() -> None:
    service = ExecutionService()
    plan = make_trade_plan()
    execution = service.execute_trade_plan(plan)

    assert execution.status is ExecutionStatus.PROTECTIVE_ORDERS_PLANNED
    assert service.get_execution_by_id(execution.execution_id) == execution
    assert service.get_execution_by_trade_plan_id(plan.trade_plan_id) == execution
    assert service.get_filled_executions("BTCUSDT") == (execution,)


def test_duplicate_execution_rejected_and_cancel_api() -> None:
    service = ExecutionService()
    plan = make_trade_plan()
    service.execute_trade_plan(plan)
    duplicate = service.execute_trade_plan(plan)

    assert duplicate.status is ExecutionStatus.REJECTED
    assert duplicate.rejection_reason is ExecutionRejectionReason.DUPLICATE_EXECUTION
    cancelled = service.cancel_execution(duplicate.execution_id, "cleanup")
    assert cancelled.status is ExecutionStatus.CANCELLED


def test_duplicate_rejection_does_not_replace_original_execution() -> None:
    service = ExecutionService()
    plan = make_trade_plan()
    original = service.execute_trade_plan(plan)
    duplicate = service.execute_trade_plan(plan)

    assert duplicate.execution_id != original.execution_id
    assert service.get_execution_by_trade_plan_id(plan.trade_plan_id) == original


def test_status_query_and_mark_status() -> None:
    service = ExecutionService()
    execution = service.execute_trade_plan(make_trade_plan())
    updated = service.mark_execution_status(execution.execution_id, ExecutionStatus.FAILED, execution.created_at + timedelta(minutes=1), "test")

    assert service.get_executions_by_status(ExecutionStatus.FAILED) == (updated,)
