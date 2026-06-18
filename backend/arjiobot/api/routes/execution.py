"""Paper execution routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.execution.execution_models import execution_to_record

router = APIRouter(prefix="/api/execution", tags=["execution"])


@router.post("/paper/{trade_plan_id}")
def paper_execute(trade_plan_id: str, payload: dict[str, object] | None = None):
    state = get_state()
    plan = state.trade_plans.get(trade_plan_id)
    if plan is None:
        raise api_error(404, "TRADE_PLAN_NOT_FOUND", "trade plan not found")
    execution = state.execution_service.execute_trade_plan(plan)
    return ok(execution_to_record(execution))


@router.get("/records")
def records():
    return ok(tuple(execution_to_record(execution) for execution in get_state().execution_service.store.executions.values()))


@router.get("/records/{execution_id}")
def get_record(execution_id: str):
    execution = get_state().execution_service.get_execution_by_id(execution_id)
    if execution is None:
        raise api_error(404, "EXECUTION_NOT_FOUND", "execution record not found")
    return ok(execution_to_record(execution))


@router.post("/cancel/{execution_id}")
def cancel(execution_id: str, payload: dict[str, object] | None = None):
    return ok(execution_to_record(get_state().execution_service.cancel_execution(execution_id, "api-cancel")))
