"""Radar routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.schemas.common import ok
from arjiobot.backtesting.research_profiles import DEFAULT_PROFILE_ID, get_profile

router = APIRouter(prefix="/api/radar", tags=["radar"])


def radar_record(setup) -> dict[str, object]:
    profile_status = getattr(setup, "profile_f_status", {}) or {}
    strategy_profile = str(profile_status.get("strategy_profile") or get_state().settings.get("active_strategy_profile") or DEFAULT_PROFILE_ID)
    try:
        active_profile = get_profile(strategy_profile)
    except ValueError:
        active_profile = get_profile(DEFAULT_PROFILE_ID)
    return {
        "setup_id": setup.setup_id,
        "symbol": setup.symbol,
        "direction": setup.direction.value,
        "strategy_profile": active_profile.profile_id,
        "profile_variant_name": active_profile.label,
        "inherited_base_profile": profile_status.get("inherited_base_profile", active_profile.inherited_base_profile),
        "expansion_min": active_profile.expansion_ratio_min,
        "expansion_max": active_profile.expansion_ratio_max,
        "retracement_window": active_profile.retrace_window_8m_candles,
        "entry_model": "DIRECT_12M_RETRACE" if active_profile.direct_12m_retrace_entry_enabled else "FULL_1M_CONFIRMATION",
        "current_state": setup.current_state.value,
        "progress_percent": setup.progress_percent,
        "setup_percentage": profile_status.get("setup_percentage", setup.progress_percent),
        "missing_requirements": [],
        "invalidation_reason": setup.invalidation_reason.value if setup.invalidation_reason else None,
        "time_remaining": None,
        "stop_reference": str(setup.stop_reference_price) if getattr(setup, "stop_reference_price", None) else None,
        "target_reference": str(setup.final_target_price) if getattr(setup, "final_target_price", None) else None,
        "higher_timeframe_context_status": profile_status.get("higher_timeframe_context_status"),
        "fvg_16m_status": profile_status.get("fvg_16m_status"),
        "expansion_ratio": profile_status.get("expansion_ratio"),
        "fvg_12m_status": profile_status.get("fvg_12m_status"),
        "eight_minute_candle_count_after_16m_fvg": profile_status.get("eight_minute_candle_count_after_16m_fvg"),
        "retracement_within_3_8m_candles": profile_status.get("retracement_within_3_8m_candles", profile_status.get("retracement_within_deadline")),
        "first_candle_entered_12m_fvg": profile_status.get("first_candle_entered_12m_fvg"),
        "entry_candle_boundary_respected": profile_status.get("entry_candle_boundary_respected"),
        "entry_ready": setup.current_state.value == "ENTRY_READY",
        "one_trade_per_fvg_status": profile_status.get("one_trade_per_fvg_status", "ENFORCED"),
        "rejection_reason": profile_status.get("rejection_reason") or (setup.invalidation_reason.value if setup.invalidation_reason else None),
    }


@router.get("")
def radar():
    return ok(tuple(radar_record(setup) for setup in get_state().setups.values()))


@router.get("/live")
def live_radar():
    state = get_state()
    if not state.monitoring.get("active"):
        return ok({"status": "NOT MONITORING", "message": "NO ACTIVE LIVE SETUPS", "setups": ()})
    setups = tuple({**radar_record(setup), "source": "LIVE_MARKET_DATA"} for setup in state.setups.values())
    return ok({"status": "ACTIVE" if setups else "WAITING", "message": "NO ACTIVE LIVE SETUPS" if not setups else "LIVE SETUPS ACTIVE", "setups": setups})
