"""Mobile control dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import FROZEN_VISIBLE_PROFILE_ID, get_state, save_settings
from arjiobot.api.schemas.common import ok

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


@router.get("/control-status")
def control_status():
    state = get_state()
    settings = state.settings
    executions = tuple(state.execution_service.store.executions.values())
    open_executions = tuple(
        execution
        for execution in executions
        if str(getattr(execution, "status", "")).upper() not in {"CANCELLED", "FAILED", "FILLED", "REJECTED"}
    )
    return ok(
        {
            "engine_host": "VPS_SERVER",
            "phone_role": "CONTROL_DASHBOARD_ONLY",
            "trading_mode": settings.get("trading_mode", "OFF"),
            "live_trading_enabled": settings.get("live_trading_enabled", False),
            "environment_lock_verified": settings.get("environment_lock_verified", "NO"),
            "selected_profile": settings.get("active_strategy_profile", FROZEN_VISIBLE_PROFILE_ID),
            "visible_profile": FROZEN_VISIBLE_PROFILE_ID,
            "starting_balance": settings.get("starting_balance", ""),
            "fixed_risk_amount": settings.get("risk_amount_per_trade", ""),
            "max_leverage": settings.get("max_leverage", ""),
            "max_daily_loss": settings.get("max_daily_loss", ""),
            "max_weekly_loss": settings.get("max_weekly_loss", ""),
            "enabled_pairs": tuple(pair["symbol"] for pair in state.monitored_pairs.values() if pair.get("enabled")),
            "trade_plans_count": len(state.trade_plans),
            "execution_records_count": len(executions),
            "open_positions_count": len(open_executions),
            "recent_logs": tuple(event for event in state.bitget_environment.mode_events[-12:]),
        }
    )


@router.post("/emergency-stop")
def emergency_stop(payload: dict[str, object] | None = None):
    state = get_state()
    result = state.bitget_environment.switch_mode("OFF")
    state.settings["trading_mode"] = "OFF"
    state.settings["live_trading_enabled"] = False
    state.settings["environment_lock_verified"] = result.get("environment_lock_verified", "NO")
    save_settings(state.settings)
    return ok(
        {
            "emergency_stop": "ENGAGED",
            "trading_mode": "OFF",
            "live_trading_enabled": False,
            "message": "Emergency stop engaged. Trading mode switched to OFF on the server.",
        }
    )
