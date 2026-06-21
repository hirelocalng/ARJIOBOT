"""Radar routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.schemas.common import ok
from arjiobot.backtesting.research_profiles import DEFAULT_PROFILE_ID, get_profile

router = APIRouter(prefix="/api/radar", tags=["radar"])

# Stage thresholds match _ATTEMPT_STAGE_TO_STATE / the progress values
# _attempt_traces_for_direction assigns in scripts/backtest_csv.py: swing=20,
# expansion=35, 16M FVG=50, 12M FVG=65, 8M FVG/retrace=80, entry=100. progress
# is a monotonic high-water mark that can only advance by passing each prior
# stage's check in order, so "progress_percent >= threshold" is an accurate,
# always-in-sync way to answer "did this specific stage pass" - unlike the
# stage columns below before this fix, which read a profile_f_status
# attribute no Setup instance has ever set, so they always rendered as
# whatever placeholder the frontend falls back to (typically "WAITING"),
# regardless of how far the attempt actually got.
_EXPANSION_STAGE_THRESHOLD = 35.0
_FVG_16M_STAGE_THRESHOLD = 50.0
_FVG_12M_STAGE_THRESHOLD = 65.0
_FVG_8M_STAGE_THRESHOLD = 80.0
_ENTRY_STAGE_THRESHOLD = 100.0


def _stage_status(progress_percent: float, threshold: float) -> str:
    return "CONFIRMED" if progress_percent >= threshold else "WAITING"


def radar_record(setup) -> dict[str, object]:
    profile_status = getattr(setup, "profile_f_status", {}) or {}
    metadata = getattr(setup, "metadata", {}) or {}
    strategy_profile = str(profile_status.get("strategy_profile") or metadata.get("strategy_profile") or get_state().settings.get("active_strategy_profile") or DEFAULT_PROFILE_ID)
    try:
        active_profile = get_profile(strategy_profile)
    except ValueError:
        active_profile = get_profile(DEFAULT_PROFILE_ID)
    # A COMPLETED attempt-trace row and the real trade candidate
    # live_setup_detection.py found for the same swing are two different
    # Setup objects (see _apply_one_attempt_trace vs _setup_from_trade) - if
    # the real one was skipped for no longer being fresh, that fact lives in
    # state.stale_trade_skips, keyed by the swing_16m_id both rows share.
    stale_skip = get_state().stale_trade_skips.get(setup.swing_16m_id or "")
    return {
        "setup_id": setup.setup_id,
        "symbol": setup.symbol,
        "direction": setup.direction.value,
        "status": setup.status.value,
        "strategy_profile": active_profile.profile_id,
        "profile_variant_name": active_profile.label,
        "inherited_base_profile": profile_status.get("inherited_base_profile", active_profile.inherited_base_profile),
        "timeframe_profile": metadata.get("timeframe_profile"),
        "selected_tp_model": metadata.get("selected_tp_model"),
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
        "created_at": setup.created_at.isoformat() if getattr(setup, "created_at", None) else None,
        "updated_at": setup.updated_at.isoformat() if getattr(setup, "updated_at", None) else None,
        "invalidated_at": setup.invalidated_at.isoformat() if getattr(setup, "invalidated_at", None) else None,
        "entry_price": metadata.get("entry_signal_price") or metadata.get("latest_price"),
        "swing_16m_id": setup.swing_16m_id,
        "expansion_16m_id": setup.expansion_16m_id,
        "fvg_16m_id": setup.fvg_16m_id,
        "fvg_12m_id": setup.fvg_12m_id,
        "fvg_8m_id": setup.fvg_8m_id,
        "stop_reference": str(setup.stop_reference_price) if getattr(setup, "stop_reference_price", None) else None,
        "target_reference": str(setup.final_target_price) if getattr(setup, "final_target_price", None) else None,
        "higher_timeframe_context_status": profile_status.get("higher_timeframe_context_status"),
        "fvg_16m_status": profile_status.get("fvg_16m_status") or _stage_status(setup.progress_percent, _FVG_16M_STAGE_THRESHOLD),
        "expansion_ratio": profile_status.get("expansion_ratio") or _stage_status(setup.progress_percent, _EXPANSION_STAGE_THRESHOLD),
        "fvg_12m_status": profile_status.get("fvg_12m_status") or _stage_status(setup.progress_percent, _FVG_12M_STAGE_THRESHOLD),
        "eight_minute_candle_count_after_16m_fvg": profile_status.get("eight_minute_candle_count_after_16m_fvg") or _stage_status(setup.progress_percent, _FVG_8M_STAGE_THRESHOLD),
        "retracement_within_3_8m_candles": profile_status.get("retracement_within_3_8m_candles", profile_status.get("retracement_within_deadline", setup.progress_percent >= _FVG_8M_STAGE_THRESHOLD)),
        "first_candle_entered_12m_fvg": profile_status.get("first_candle_entered_12m_fvg", setup.progress_percent >= _FVG_8M_STAGE_THRESHOLD),
        "entry_candle_boundary_respected": profile_status.get("entry_candle_boundary_respected", setup.progress_percent >= _ENTRY_STAGE_THRESHOLD),
        "entry_ready": setup.current_state.value == "ENTRY_READY",
        "one_trade_per_fvg_status": profile_status.get("one_trade_per_fvg_status", "ENFORCED"),
        "rejection_reason": profile_status.get("rejection_reason") or (setup.invalidation_reason.value if setup.invalidation_reason else None),
        "source": metadata.get("source"),
        "stale_skip": stale_skip,
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


@router.get("/history")
def radar_history():
    """Latest tracked setup attempts (up to the 100-attempt cap), newest first.

    Includes every status - active, entry-ready, invalidated, expired, completed -
    so failed/invalidated attempts remain visible until pushed out by the cap.
    """
    setups = sorted(get_state().setups.values(), key=lambda setup: setup.created_at, reverse=True)
    return ok(tuple(radar_record(setup) for setup in setups))
