"""Paper executor tests."""

from __future__ import annotations

from arjiobot.execution.demo_execution import make_trade_plan
from arjiobot.execution.execution_models import ExecutionStatus, OrderSide, OrderType
from arjiobot.execution.order_builder import build_order_instruction
from arjiobot.execution.paper_executor import ExchangeExecutionAdapter, paper_execute, plan_protective_orders


def test_protective_order_plans_created() -> None:
    plan = make_trade_plan()
    execution = paper_execute(build_order_instruction(plan))

    assert execution.status is ExecutionStatus.PROTECTIVE_ORDERS_PLANNED
    assert len(execution.protective_orders) == 2
    assert execution.protective_orders[0].side is OrderSide.BUY
    assert {order.order_type for order in execution.protective_orders} == {OrderType.STOP, OrderType.TAKE_PROFIT}
    triggers = {order.order_type: order.trigger_price for order in execution.protective_orders}
    assert triggers[OrderType.STOP] == plan.stop_loss_price
    assert triggers[OrderType.TAKE_PROFIT] == plan.take_profit_price


def test_future_adapter_boundary_exists() -> None:
    method_names = set(ExchangeExecutionAdapter.__dict__)

    assert {"set_leverage", "place_market_order", "place_stop_loss", "place_take_profit", "cancel_order", "fetch_order_status"} <= method_names


def test_protective_order_planning_requires_filled_execution() -> None:
    fill = paper_execute(build_order_instruction(make_trade_plan()))
    unfilled = type(fill)(**{field: getattr(fill, field) for field in fill.__dataclass_fields__} | {"fill_price": None})

    try:
        plan_protective_orders(unfilled)
    except ValueError as error:
        assert "filled execution" in str(error)
    else:
        raise AssertionError("unfilled execution should not plan protective orders")
