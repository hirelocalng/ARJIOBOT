"""Radar routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.schemas.common import ok
from arjiobot.backtesting.research_profiles import DEFAULT_PROFILE_ID, get_profile
from arjiobot.setup_tracker.setup_history_store import filter_and_cap_history

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


# Setup Radar spec stage names/percentages, exposed via current_stage/progress_pct
# below. Internal SetupState/progress_percent stays on its own existing 20/35/
# 50/65/80/100 scale (used everywhere else - eviction ordering, tests, the
# is_terminal/invalidation wiring in live_setup_detection.py) so none of that
# tested machinery has to change; this is a pure display-layer translation.
_DISPLAY_STAGE_BY_INTERNAL_STATE: dict[str, tuple[str, float]] = {
    "SWING_16M_CONFIRMED": ("16M_SWING_DETECTED", 10.0),
    "EXPANSION_16M_CONFIRMED": ("16M_EXPANSION_DETECTED", 25.0),
    "FVG_16M_CONFIRMED": ("16M_FVG_DETECTED", 40.0),
    "FVG_12M_CONFIRMED": ("12M_FVG_DETECTED", 55.0),
    "FVG_8M_CONFIRMED": ("8M_FVG_DETECTED", 70.0),
    "ENTRY_READY": ("ENTRY_READY", 100.0),
    "COMPLETED": ("ENTRY_READY", 100.0),
    "INVALIDATED": ("INVALIDATED", None),
    "EXPIRED": ("EXPIRED", None),
}


def _is_waiting_retrace(stage_value: str, setup) -> bool:
    """FVG_8M_CONFIRMED covers both "8M FVG just confirmed" and "retrace candle
    found, now waiting for the entry tap" today - distinguished only by the
    retrace_candle_found flag _attempt_traces_for_direction sets on the trace
    (carried into setup.metadata by _apply_one_attempt_trace)."""
    return stage_value == "FVG_8M_CONFIRMED" and (setup.metadata or {}).get("retrace_candle_found") == "YES"


def _display_current_stage(setup) -> str:
    """current_stage label from the Setup Radar spec (e.g. "16M_SWING_DETECTED",
    ..., "WAITING_RETRACE", "ENTRY_READY"). Internal SetupState/progress_percent
    are left on their own existing 20/35/50/65/80/100 scale (used by eviction
    ordering, tests, and the invalidation wiring in live_setup_detection.py) -
    this is a pure display-layer translation, not a rename."""
    state_value = setup.current_state.value
    if _is_waiting_retrace(state_value, setup):
        return "WAITING_RETRACE"
    stage, _progress = _DISPLAY_STAGE_BY_INTERNAL_STATE.get(state_value, (state_value, None))
    return stage


def _display_progress_pct(setup) -> float:
    """progress_pct on the spec's 10/25/40/55/70/85/100 scale. For an
    INVALIDATED/EXPIRED setup this reflects the high-water mark stage reached
    before failure (last_valid_stage), not the terminal INVALIDATED/EXPIRED
    state itself, matching the "% reached before invalidation" the Invalidated
    tab asks for."""
    state_value = setup.current_state.value
    if state_value in ("INVALIDATED", "EXPIRED"):
        state_value = setup.last_valid_stage or "SWING_16M_CONFIRMED"
    if _is_waiting_retrace(state_value, setup):
        return 85.0
    _stage, progress = _DISPLAY_STAGE_BY_INTERNAL_STATE.get(state_value, (state_value, None))
    return progress if progress is not None else setup.progress_percent


def _display_last_valid_stage(setup) -> str | None:
    last_valid_stage = getattr(setup, "last_valid_stage", None)
    if not last_valid_stage:
        return None
    if _is_waiting_retrace(last_valid_stage, setup):
        return "WAITING_RETRACE"
    stage, _progress = _DISPLAY_STAGE_BY_INTERNAL_STATE.get(last_valid_stage, (last_valid_stage, None))
    return stage


def _related_execution(setup) -> dict[str, object] | None:
    """Best-effort link from a COMPLETED/ENTRY_READY setup to the real Bitget
    order live automation submitted for it, if any. live_automation.py's
    attempts list already carries setup_id on every record (see
    _process_setup), so this is a lookup, not new tracking - but it is
    capped at the latest 50 attempts (_append_attempt), so a setup whose
    trade happened long enough ago may no longer have a matching entry even
    though the trade itself did go through.
    """
    attempts = getattr(get_state(), "live_automation", {}).get("attempts", [])
    for attempt in reversed(attempts):
        if attempt.get("setup_id") == setup.setup_id and attempt.get("status") == "SUBMITTED":
            return {
                "trade_plan_id": attempt.get("trade_plan_id"),
                "bitget_order_id": attempt.get("bitget_order_id"),
                "submitted_at": attempt.get("submitted_at"),
            }
    return None


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
    # Setup objects (see _apply_one_attempt_trace vs _setup_from_trade);
    # _suppress_redundant_attempt_trace removes the former once the latter
    # exists, so only one should ever be visible per swing in steady state.
    # state.stale_trade_skips (keyed by swing_16m_id) is now only populated
    # when more than one swing resolved to ENTRY_READY in the same poll -
    # this swing's real trade is queued behind whichever was picked first
    # this poll, not abandoned; it is picked up automatically on a later poll.
    stale_skip = get_state().stale_trade_skips.get(setup.swing_16m_id or "")
    related_execution = _related_execution(setup)
    return {
        "setup_id": setup.setup_id,
        "symbol": setup.symbol,
        "direction": setup.direction.value,
        "status": setup.status.value,
        # Setup Radar spec field names (current_stage/progress_pct/
        # last_valid_stage/swing_detected_at/last_updated_at/execution_id/
        # trade_id/rr_tp_profile), additive alongside the existing
        # current_state/progress_percent/created_at/updated_at fields the
        # frontend already reads - see _display_current_stage's docstring for
        # why this is a display translation, not a rename of the internal
        # SetupState scale.
        "current_stage": _display_current_stage(setup),
        "progress_pct": _display_progress_pct(setup),
        "last_valid_stage": _display_last_valid_stage(setup),
        "swing_detected_at": setup.created_at.isoformat() if getattr(setup, "created_at", None) else None,
        "last_updated_at": setup.updated_at.isoformat() if getattr(setup, "updated_at", None) else None,
        "execution_id": (related_execution or {}).get("bitget_order_id"),
        "trade_id": (related_execution or {}).get("trade_plan_id"),
        "rr_tp_profile": metadata.get("selected_tp_model"),
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
        "completed_at": setup.completed_at.isoformat() if getattr(setup, "completed_at", None) else None,
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
        # None while a real ENTRY_READY setup is still "pending execution" in
        # IN PROGRESS - one of TERMINAL_EXECUTION_STATES (trade_opened/
        # rejected/risk_blocked/no_margin/invalidated/expired) once
        # execution has resolved it either way (see should_leave_in_progress,
        # setup_tracker/setup_models.py).
        "execution_status": getattr(setup, "execution_status", None),
        "one_trade_per_fvg_status": profile_status.get("one_trade_per_fvg_status", "ENFORCED"),
        "rejection_reason": profile_status.get("rejection_reason") or (setup.invalidation_reason.value if setup.invalidation_reason else None),
        "source": metadata.get("source"),
        "stale_skip": stale_skip,
        "swing_price": metadata.get("swing_price") or None,
        "related_execution": related_execution,
    }


def _all_setups(state) -> tuple:
    """Every tracked setup across all three stores - in-progress (uncapped),
    invalidated (age-filtered + capped at 100), completed (age-filtered +
    capped at 100). filter_and_cap_history is read-only - applied here
    defensively, since wall-clock time alone can push a setup past the
    1-hour age limit between writes."""
    return (*state.setups.values(), *filter_and_cap_history(state.invalidated_setups).values(), *filter_and_cap_history(state.completed_setups).values())


@router.get("")
def radar():
    return ok(tuple(radar_record(setup) for setup in _all_setups(get_state())))


@router.get("/live")
def live_radar():
    state = get_state()
    if not state.monitoring.get("active"):
        return ok({"status": "NOT MONITORING", "message": "NO ACTIVE LIVE SETUPS", "setups": ()})
    setups = tuple({**radar_record(setup), "source": "LIVE_MARKET_DATA"} for setup in _all_setups(state))
    return ok({"status": "ACTIVE" if setups else "WAITING", "message": "NO ACTIVE LIVE SETUPS" if not setups else "LIVE SETUPS ACTIVE", "setups": setups})


@router.get("/history")
def radar_history():
    """Latest tracked setup attempts across all three stores, newest first.

    Includes every status - active, entry-ready, invalidated, expired, completed -
    so failed/invalidated attempts remain visible until pushed out by their
    own store's 100-cap (in-progress/entry-ready is not capped).
    """
    setups = sorted(_all_setups(get_state()), key=lambda setup: setup.created_at, reverse=True)
    return ok(tuple(radar_record(setup) for setup in setups))
