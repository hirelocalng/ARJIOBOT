"""Health/status routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.schemas.common import ok
from arjiobot.backtesting.research_profiles import DEFAULT_PROFILE_ID
from arjiobot.backtesting.timeframe_profiles import get_timeframe_profile
from arjiobot.risk.rr_profiles import resolve_rr_value
from pathlib import Path

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    state = get_state()
    return ok(
        {
            "status": "healthy",
            "backend_running": True,
            "database_connected": False,
            "adapter_mode": state.settings["adapter_mode"],
            "live_trading_enabled": state.settings["live_trading_enabled"],
            "strategy_profile": str(state.settings.get("active_strategy_profile", DEFAULT_PROFILE_ID)),
        }
    )


@router.get("/status")
def status():
    state = get_state()
    return ok(
        {
            "api_status": "online",
            "adapter_mode": state.settings["adapter_mode"],
            "live_trading_enabled": state.settings["live_trading_enabled"],
            "monitored_pairs_count": len(state.monitored_pairs),
            "active_setups_count": len(state.setups),
            "generated_signals_count": len(state.signals),
            "approved_trade_plans_count": len(state.trade_plans),
            "execution_records_count": len(state.execution_service.store.executions),
        }
    )


@router.get("/system-status")
def system_status():
    state = get_state()
    settings = state.settings
    enabled_pairs = [pair["symbol"] for pair in state.monitored_pairs.values() if pair.get("enabled")]
    timeframe_ok = True
    rr_ok = True
    try:
        timeframe = get_timeframe_profile(str(settings.get("default_timeframe_profile")))
    except ValueError:
        timeframe = None
        timeframe_ok = False
    try:
        rr_value = resolve_rr_value(str(settings.get("selected_rr_profile")))
    except ValueError:
        rr_value = None
        rr_ok = False
    return ok(
        {
            "backend_running": True,
            "database_connected": False,
            "bitget_api_connected": bool(state.exchange_adapter.credential_store.list_exchange_accounts()),
            "selected_mode_valid": settings.get("adapter_mode") in {"MOCK", "BITGET_LIVE"},
            "selected_pairs_valid": bool(enabled_pairs),
            "enabled_pairs": enabled_pairs,
            "selected_timeframe_profile_valid": timeframe_ok,
            "selected_timeframe_profile": timeframe.to_record() if timeframe else None,
            "selected_rr_profile_valid": rr_ok,
            "selected_rr_profile": settings.get("selected_rr_profile"),
            "selected_rr_value": str(rr_value) if rr_value is not None else None,
            "fixed_risk_amount_valid": str(settings.get("risk_amount_per_trade", "0")) not in {"", "0"},
            "notification_bot_connected": False,
            "setup_radar_running": True,
            "trade_engine_running": True,
            "live_trading_enabled": settings.get("live_trading_enabled"),
            "live_trading_guarded": not bool(settings.get("live_trading_enabled")),
            "strategy_profile": str(state.settings.get("active_strategy_profile", DEFAULT_PROFILE_ID)),
        }
    )


@router.get("/strategy-compliance")
def strategy_compliance():
    root = Path(__file__).resolve().parents[4]
    report = root / "reports" / "strategy_compliance_audit.html"
    return ok({"status": "ready" if report.exists() else "pending", "report": str(report)})
