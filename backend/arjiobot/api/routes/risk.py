"""Risk routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.risk.demo_risk import default_context
from arjiobot.risk.risk_models import trade_plan_to_record

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.post("/assess/{signal_id}")
def assess(signal_id: str):
    state = get_state()
    signal = state.signals.get(signal_id)
    if signal is None:
        raise api_error(404, "SIGNAL_NOT_FOUND", "signal not found")
    config, snapshot, open_state = default_context()
    assessment = state.risk_engine.assess_signal(signal, config, snapshot, open_state)
    return ok({"assessment_id": assessment.assessment_id, "validation_passed": assessment.validation_passed, "rejection_reasons": [reason.value for reason in assessment.rejection_reasons]})


@router.post("/trade-plan/{signal_id}")
def trade_plan(signal_id: str):
    state = get_state()
    signal = state.signals.get(signal_id)
    if signal is None:
        raise api_error(404, "SIGNAL_NOT_FOUND", "signal not found")
    config, snapshot, open_state = default_context()
    plan = state.risk_engine.create_trade_plan(signal, config, snapshot, open_state)
    state.trade_plans[plan.trade_plan_id] = plan
    return ok(trade_plan_to_record(plan))


@router.get("/trade-plans")
def list_trade_plans():
    return ok(tuple(trade_plan_to_record(plan) for plan in get_state().trade_plans.values()))


@router.get("/trade-plans/{trade_plan_id}")
def get_trade_plan(trade_plan_id: str):
    plan = get_state().trade_plans.get(trade_plan_id)
    if plan is None:
        raise api_error(404, "TRADE_PLAN_NOT_FOUND", "trade plan not found")
    return ok(trade_plan_to_record(plan))
