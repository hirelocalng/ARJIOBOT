"""Live candle-to-setup detection.

The live detector reuses the same profile-aware evaluator used by CSV
backtests, then converts fresh live trade candidates into Setup Radar objects.
It does not synthesize trades; no setup is created unless the evaluator returns
a real trade candidate from live candles.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

from arjiobot.backtesting.historical_replay import build_timeframe_profile, order_historical_candles
from arjiobot.backtesting.research_profiles import get_profile
from arjiobot.backtesting.timeframe_profiles import get_timeframe_profile
from arjiobot.fvg.fvg import FVGDetectionEngine
from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe
from arjiobot.setup_tracker.setup_history_store import save_setup_history_store
from arjiobot.setup_tracker.setup_models import (
    MIN_DWELL_SECONDS,
    InvalidationReason,
    Setup,
    SetupDirection,
    SetupState,
    SetupStatus,
    StateHistoryEntry,
    build_setup_id,
    build_swing_dedup_key,
)
from arjiobot.swings.swing_models import SwingType
from arjiobot.swings.swings import SwingDetectionEngine

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "backtest_csv.py"
_RUNNER: ModuleType | None = None

MAX_TRACKED_SETUP_ATTEMPTS = 100

# A stale skip whose detection happens within this many seconds of the
# current monitoring session's started_at is classified as catching up on a
# backlog from before this session started (a restart/outage), rather than a
# gap that opened up during otherwise-continuous polling. 5 minutes is
# generous relative to the default 15s poll interval - a session that has
# been running continuously for 5+ minutes has had dozens of poll
# opportunities, so a skip that far in is far more likely to be routine
# strategy-level rejection noise than a genuine restart catch-up.
RESTART_CATCHUP_WINDOW_SECONDS = 300

# Setup Radar attempt stage -> SetupState, for every NON-terminal stage. A
# trace reaching "ENTRY_READY" is never looked up here - it is always routed
# straight to SetupState.INVALIDATED/NO_EXECUTION_ATTEMPTED instead (see
# _apply_one_attempt_trace's structural_match_only handling): the actual
# automation-triggering ENTRY_READY row is created separately by the
# existing, untouched _setup_from_trade/_fresh_trade_candidate flow below
# (which carries the RR/TP-model-aware stop/target the risk engine actually
# needs) - reaching ENTRY_READY here only means the funnel's structural
# conditions matched, never that execution made a decision (Setup Radar
# journey rule). If a trace-derived row also became ENTRY_READY,
# run_live_automation_once's `current_state is ENTRY_READY` filter could see
# two rows for the same opportunity and submit twice.
_ATTEMPT_STAGE_TO_STATE = {
    "SWING_16M_CONFIRMED": SetupState.SWING_16M_CONFIRMED,
    "EXPANSION_16M_CONFIRMED": SetupState.EXPANSION_16M_CONFIRMED,
    "FVG_16M_CONFIRMED": SetupState.FVG_16M_CONFIRMED,
    "FVG_12M_CONFIRMED": SetupState.FVG_12M_CONFIRMED,
    "FVG_8M_CONFIRMED": SetupState.FVG_8M_CONFIRMED,
}


def live_setup_detection_status(state: Any) -> dict[str, Any]:
    return dict(state.live_setup_detection)


def _fvg_engine_for(state: Any, symbol: str, minutes: int) -> FVGDetectionEngine:
    """One FVGDetectionEngine per (symbol, timeframe), reused across every
    poll instead of constructed fresh each call.

    detect_fvgs() re-scans the *entire* rolling live candle buffer (up to
    44,640 1m candles) every poll, with no memory of what it logged 15
    seconds ago - a fresh engine each call meant every already-known
    historical FVG got rediscovered and re-logged at INFO level on every
    single poll, for every monitored pair, which is what was flooding
    Railway's logs (measured: over 1,600 "FVG detected" lines from a single
    poll of a single symbol at a realistic full-session buffer size).
    fvg_id is deterministic (content-derived - see build_fvg_id), so reusing
    the same engine instance's store across polls lets detect_fvgs() log
    each genuine FVG exactly once, the first time it is ever seen, while
    still returning the identical full FVG set every call (the log line is
    the only thing this changes - see fvg.py's detect_fvgs).
    """
    key = f"{symbol.upper()}:{minutes}"
    engine = state.live_fvg_engines.get(key)
    if engine is None:
        engine = FVGDetectionEngine()
        state.live_fvg_engines[key] = engine
    return engine


def _filter_resolved_swings(state: Any, swings: list[Any], *, direction: str) -> list[Any]:
    """Setup Radar swing-level dedup (Fix 1/5): drop any swing whose
    permanent dedup key (see setup_models.build_swing_dedup_key) already
    resolved into COMPLETED/INVALIDATED/EXPIRED on an earlier poll - logged
    at DEBUG only, since this is the expected, common case once a symbol has
    been monitored for a while, not something worth surfacing at INFO every
    poll.
    """
    fresh: list[Any] = []
    for swing in swings:
        key = build_swing_dedup_key(symbol=swing.symbol, direction=direction, swing_timestamp=swing.right_candle.timestamp)
        if key in state.resolved_swing_keys:
            logger.debug("Swing %s (%s) already resolved; skipping re-evaluation this poll (key=%s)", swing.swing_id, direction, key)
            continue
        fresh.append(swing)
    return fresh


def detect_live_setups_for_symbol(state: Any, symbol: str, *, source: str = "MONITORING_POLL") -> dict[str, Any]:
    symbol = symbol.upper()
    detector_state = state.live_setup_detection
    detector_state["last_run_at"] = _now()
    detector_state["last_error"] = "None"
    try:
        candles = tuple(state.live_candles.get(symbol, ()))
        if len(candles) < 120:
            return _finish(detector_state, "WAITING", f"not enough live candles for strategy evaluation: {len(candles)}", source=source)

        profile = get_profile(str(state.settings.get("active_strategy_profile") or state.settings.get("default_backtesting_profile") or "PROFILE_2"))
        runner = _runner()
        requested_tp_model = str(state.settings.get("selected_rr_profile") or profile.tp_model).upper()
        # The exact same protection _build_strategy_funnel/_build_bullish_
        # strategy_funnel already apply internally to decide what tp_model a
        # trade is actually built with (backtest_csv.py's
        # _selected_rr_profile_for_profile - profile.tp_model always wins for
        # locked models: LEG_TARGET_RESEARCH/RR_1_0/RR_1_0_RESEARCH).
        # Resolving it here too, before it ever reaches Setup.metadata, means
        # selected_tp_model/applied_tp_model always matches what was
        # actually used to compute stop/target, instead of echoing back a
        # saved setting (e.g. RR_1_5) that the funnel itself was always
        # going to override anyway.
        selected_tp_model = runner._selected_rr_profile_for_profile(profile, requested_tp_model)
        # The saved live setting must win over the profile's built-in default - e.g.
        # PROFILE_2's built-in timeframe_profile_id must not override an operator's
        # explicit choice to run live trading on DEFAULT_16_12_8.
        timeframe_profile = get_timeframe_profile(str(state.settings.get("default_timeframe_profile") or profile.timeframe_profile_id or "DEFAULT_16_12_8"))
        logger.info(
            "Live evaluation for %s: strategy_profile=%s timeframe_profile=%s (%s) tp_model=%s%s",
            symbol,
            profile.profile_id,
            timeframe_profile.profile_id,
            timeframe_profile.label,
            selected_tp_model,
            " (structural leg target, not a fixed RR multiple)" if selected_tp_model == "LEG_TARGET_RESEARCH" else "",
        )
        required_minutes = runner._required_timeframes(timeframe_profile)
        profiles = {minutes: build_timeframe_profile(candles, minutes) for minutes in required_minutes}
        if not profiles.get(timeframe_profile.swing_timeframe) or not profiles.get(1):
            return _finish(detector_state, "WAITING", "not enough aligned candles for selected timeframe profile", source=source)

        swing_results = SwingDetectionEngine().detect_all_swings(profiles[timeframe_profile.swing_timeframe])
        # Swing-level dedup (Fix 1/5): drop any swing already permanently
        # resolved (COMPLETED/INVALIDATED/EXPIRED on an earlier poll) right
        # here, straight out of swing detection, before it is ever passed to
        # the funnel below - the earliest point its own timestamp exists,
        # and before any setup_id is minted for it this poll. The funnel
        # only ever walks the candidate lists passed in here for both
        # attempt-trace tracking and real trade detection, so filtering them
        # here is sufficient to stop a resolved swing from being
        # re-evaluated by either path at all.
        bearish_swing_highs = _filter_resolved_swings(
            state,
            [swing for swing in swing_results.swing_highs if swing.swing_type is SwingType.HIGH],
            direction="BEARISH",
        )
        bullish_swing_lows = _filter_resolved_swings(
            state,
            [swing for swing in swing_results.swing_lows if swing.swing_type is SwingType.LOW],
            direction="BULLISH",
        )
        expansions_main = runner._research_expansions(swing_results.all_swings)
        fvg_results = {
            minutes: _fvg_engine_for(state, symbol, minutes).detect_fvgs(
                profiles[minutes],
                swings=swing_results.all_swings if profile.use_linked_fvg_detection and minutes == timeframe_profile.main_fvg_timeframe else (),
                expansions=expansions_main if profile.use_linked_fvg_detection and minutes == timeframe_profile.main_fvg_timeframe else (),
            )
            for minutes in required_minutes
            if minutes != 1
        }
        shared_funnel_kwargs = dict(
            profile=profile,
            timeframe_profile=timeframe_profile,
            expansions_16m=expansions_main,
            fvg_16m=fvg_results[timeframe_profile.main_fvg_timeframe].fvgs,
            fvg_12m=fvg_results[timeframe_profile.retrace_fvg_timeframe].fvgs,
            fvg_8m=fvg_results[timeframe_profile.internal_fvg_timeframe].fvgs,
            candles_8m=profiles[timeframe_profile.retrace_window_timeframe],
            candles_1m=profiles[1],
            starting_balance=state.settings.get("starting_balance") or "1",
            risk_amount_per_trade=state.settings.get("risk_amount_per_trade"),
            max_leverage=state.settings.get("max_leverage"),
            # TIME_BASED_EXIT is an exit *mechanism* (close on a timer,
            # handled separately via metadata's time_exit_enabled/
            # time_exit_minutes below), not a tp_model the funnel itself
            # knows how to size a target with - fall back to the profile's
            # own tp_model for the underlying stop/target math in that case.
            # selected_tp_model is already protected the same way the funnel
            # protects it internally, so no separate re-derivation needed.
            selected_rr_profile=profile.tp_model if selected_tp_model == "TIME_BASED_EXIT" else selected_tp_model,
        )
        # Sell-side (bearish, swing-high) and buy-side (bullish, swing-low) funnels run
        # side by side through the same shared strategy logic - see scripts/backtest_csv.py
        # _build_strategy_funnel / _build_bullish_strategy_funnel. Neither path is favored.
        # Each direction is built and processed in full isolation (see _detect_for_direction)
        # so a bug surfacing in one direction's funnel can never block the other - in
        # particular, a problem in the newer bullish path must never degrade the
        # proven bearish path's ability to keep taking trades, and vice versa.
        created_setup_ids: list[str] = []
        waiting_reasons: list[str] = []
        direction_errors: list[str] = []
        for direction, builder, candidate_swings, compact_kwargs in (
            ("BEARISH", runner._build_strategy_funnel, {"candidate_16m_swing_highs": bearish_swing_highs}, {}),
            ("BULLISH", runner._build_bullish_strategy_funnel, {"candidate_16m_swing_lows": bullish_swing_lows}, {"direction": "BULLISH"}),
        ):
            try:
                funnel = builder(**candidate_swings, **shared_funnel_kwargs)
            except Exception as exc:
                logger.exception("Live %s funnel evaluation for %s failed; other direction is unaffected", direction, symbol)
                detector_state.setdefault("latest_funnel", {})[direction.lower()] = {"error": str(exc)}
                direction_errors.append(f"{direction}: {exc}")
                continue
            detector_state.setdefault("latest_funnel", {})[direction.lower()] = _compact_funnel(funnel, **compact_kwargs)
            _log_retrace_diagnostics(symbol, funnel, direction=direction)

            try:
                _apply_attempt_traces(
                    state,
                    symbol,
                    funnel.get("attempt_traces", ()),
                    profile_id=profile.profile_id,
                    timeframe_profile_id=timeframe_profile.profile_id,
                    selected_tp_model=selected_tp_model,
                    source=source,
                )
            except Exception:
                # Setup Radar visibility must never block the proven entry-ready
                # trade flow below - that flow is untouched and runs regardless.
                logger.exception("Failed to apply Setup Radar attempt traces for %s (%s); entry-ready detection continues", symbol, direction)

            fresh = _fresh_trade_candidate(funnel.get("trade_list", ()), candles, detector_state)
            if fresh is None:
                waiting_reasons.append(f"{direction}: no fresh live trade candidate found")
                continue

            # Any other never-seen candidate this same poll besides the one just
            # picked - this only happens when more than one swing resolves to
            # ENTRY_READY in the same poll (e.g. a genuine restart/outage backlog
            # surfacing at once). It is purely a visibility diagnostic now: each
            # one will still be picked up and acted on, one per poll, on a
            # subsequent pass - nothing here blocks execution.
            queued = _stale_trade_candidates(funnel.get("trade_list", ()), candles, detector_state, exclude=fresh)
            if queued:
                _record_stale_skip(symbol, queued, detector_state)
                _record_stale_skips_for_radar(state, queued)

            setup = _setup_from_trade(
                fresh,
                state=state,
                profile_id=profile.profile_id,
                timeframe_profile_id=timeframe_profile.profile_id,
                selected_tp_model=selected_tp_model,
                time_exit_minutes=str(state.settings.get("time_exit_minutes") or "30"),
            )
            # A swing whose very first poll ever observed already produces a
            # real, tradable ENTRY_READY trade (no earlier attempt-tracer
            # history for it yet) must still be recorded in IN PROGRESS
            # before this real setup is stored - otherwise it would go
            # straight from never-seen to ENTRY_READY/COMPLETED without ever
            # appearing in IN PROGRESS history.
            _record_in_progress_before_terminal_move(
                state,
                setup_id=setup.setup_id,
                symbol=setup.symbol,
                direction=setup.direction,
                created_at=setup.created_at,
                current_state=SetupState.FVG_8M_CONFIRMED,
                progress_percent=80.0,
                swing_16m_id=setup.swing_16m_id,
                expansion_16m_id=setup.expansion_16m_id,
                fvg_16m_id=setup.fvg_16m_id,
                fvg_12m_id=setup.fvg_12m_id,
                metadata=setup.metadata,
                now=setup.updated_at,
                source=source,
            )
            # setup.setup_id may already be tracked - the attempt-tracer's row
            # for this exact swing (see _find_tracked_setup_by_swing), which
            # can itself already be resolved (COMPLETED this same poll, or
            # INVALIDATED/COMPLETED from an earlier poll if this trade was
            # queued behind another candidate and only picked up now - see
            # _stale_trade_candidates) - so remove it from whichever store
            # currently holds it, and un-resolve its setup_id (it is about to
            # become a real, freshly-tracked IN PROGRESS row again, taking
            # over its own tracked identity instead of appearing as a second,
            # separate row next to it).
            state.setups.pop(setup.setup_id, None)
            state.invalidated_setups[:] = [tracked for tracked in state.invalidated_setups if tracked.setup_id != setup.setup_id]
            state.completed_setups[:] = [tracked for tracked in state.completed_setups if tracked.setup_id != setup.setup_id]
            state.resolved_setup_ids.discard(setup.setup_id)
            _suppress_redundant_attempt_trace(state, setup.swing_16m_id)  # defensive backstop; normally a no-op now
            state.setups[setup.setup_id] = setup
            state.setup_history.setdefault(setup.setup_id, []).append(
                {
                    "from_state": None,
                    "to_state": SetupState.ENTRY_READY.value,
                    "changed_at": setup.updated_at.isoformat(),
                    "reason": "live profile evaluator created entry-ready setup",
                    "source": source,
                }
            )
            detector_state.setdefault("processed_trade_keys", []).append(_trade_key(fresh))
            del detector_state["processed_trade_keys"][:-200]
            detector_state["created_setup_count"] = int(detector_state.get("created_setup_count") or 0) + 1
            detector_state["latest_trade_candidate"] = {key: str(fresh.get(key, "")) for key in ("trade_id", "symbol", "direction", "entry_timestamp", "entry_price", "stop_loss", "take_profit", "source_12m_fvg_id")}
            created_setup_ids.append(setup.setup_id)

        if created_setup_ids:
            return _finish(detector_state, "SETUP_CREATED", f"created ENTRY_READY setup(s): {', '.join(created_setup_ids)}", source=source)
        if direction_errors and len(direction_errors) == 2:
            detector_state["last_status"] = "ERROR"
            detector_state["last_error"] = "; ".join(direction_errors)
            detector_state["last_blocked_reason"] = "; ".join(direction_errors)
            return {"source": source, "status": "ERROR", "reason": "; ".join(direction_errors), "created_at": _now()}
        return _finish(detector_state, "WAITING", "; ".join(waiting_reasons + direction_errors) or "no fresh live trade candidate found", source=source)
    except Exception as exc:
        detector_state["last_status"] = "ERROR"
        detector_state["last_error"] = str(exc)
        detector_state["last_blocked_reason"] = str(exc)
        return {"source": source, "status": "ERROR", "reason": str(exc), "created_at": _now()}


def candles_from_bitget_rows(symbol: str, rows: tuple[tuple[str, ...], ...]) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    for row in rows:
        if len(row) < 6:
            continue
        timestamp = _parse_bitget_timestamp(row[0])
        if timestamp + Timeframe(1).duration > datetime.now(timezone.utc):
            continue
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=Timeframe(1),
                timestamp=timestamp,
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
                volume=Decimal(row[5]),
                status=CandleStatus.CLOSED,
            )
        )
    return order_historical_candles(candles)


def _find_tracked_setup_by_swing(state: Any, swing_16m_id: str) -> Any | None:
    """Look up the attempt-tracer's row for this swing (see
    _apply_one_attempt_trace), wherever it currently lives, so
    _setup_from_trade can take over that exact object's setup_id instead of
    minting a new one - the real setup keeps the same identity it had
    throughout Setup Radar's IN_PROGRESS tracking, rather than appearing as a
    separate row that the old/now-backstop _suppress_redundant_attempt_trace
    had to delete.

    Only ever matches a tracer-sourced row (source != LIVE_PROFILE_EVALUATOR)
    - a row already belonging to a real trade must never be reused/
    overwritten here; _fresh_trade_candidate's processed_trade_keys already
    prevents the same real trade from reaching _setup_from_trade twice.

    completed_setups/invalidated_setups are append-only lists, not dicts
    keyed by setup_id (see ApiState) - state.setups is still a dict.
    """
    if not swing_16m_id:
        return None
    for setup in state.setups.values():
        if setup.swing_16m_id == swing_16m_id and setup.metadata.get("source") != "LIVE_PROFILE_EVALUATOR":
            return setup
    for setup in (*state.completed_setups, *state.invalidated_setups):
        if setup.swing_16m_id == swing_16m_id and setup.metadata.get("source") != "LIVE_PROFILE_EVALUATOR":
            return setup
    return None


def _setup_from_trade(trade: dict[str, object], *, state: Any, profile_id: str, timeframe_profile_id: str, selected_tp_model: str = "", time_exit_minutes: str = "") -> Setup:
    entry_time = datetime.fromisoformat(str(trade["entry_timestamp"]).replace("Z", "+00:00"))
    direction = SetupDirection.BEARISH if str(trade.get("direction", "BEARISH")).upper() == "BEARISH" else SetupDirection.BULLISH
    swing_16m_id = str(trade.get("source_16m_swing_id") or "")
    tracked = _find_tracked_setup_by_swing(state, swing_16m_id)
    if tracked is not None:
        setup_id = tracked.setup_id
        created_at = tracked.created_at
    else:
        setup_id = build_setup_id(
            symbol=str(trade["symbol"]),
            direction=direction,
            created_at=entry_time,
            htf_fvg_id=str(trade.get("source_16m_fvg_id") or trade.get("source_12m_fvg_id") or ""),
        )
        created_at = entry_time
    snapshot = trade.get("setup_snapshot") if isinstance(trade.get("setup_snapshot"), dict) else {}
    expansion = snapshot.get("expansion") if isinstance(snapshot.get("expansion"), dict) else {}
    htf_fvg_id = str(trade.get("source_16m_fvg_id") or trade.get("source_12m_fvg_id") or "")
    fvg_16m_id = str(trade.get("source_16m_fvg_id") or "")
    fvg_12m_id = str(trade.get("source_12m_fvg_id") or trade.get("12m_fvg_id") or "")
    # The one place an FVG actually becomes a real setup's anchor - everything
    # detect_fvgs() finds is internal engine noise (logged at DEBUG, see
    # fvg.py), this is the moment any of it is promoted to INFO, because this
    # is the only FVG activity that should be visible in Railway's log
    # stream without hundreds of irrelevant detections drowning it out.
    logger.info(
        "FVG anchor selected for setup %s %s/%s - 16M FVG=%s 12M FVG=%s",
        setup_id,
        str(trade["symbol"]),
        direction.value,
        fvg_16m_id,
        fvg_12m_id,
    )
    return Setup(
        setup_id=setup_id,
        symbol=str(trade["symbol"]),
        direction=direction,
        current_state=SetupState.ENTRY_READY,
        progress_percent=100.0,
        status=SetupStatus.ENTRY_READY,
        created_at=created_at,
        updated_at=entry_time,
        completed_at=entry_time,
        htf_fvg_id=htf_fvg_id,
        swing_16m_id=swing_16m_id,
        expansion_16m_id=str(expansion.get("expansion_id") or "verified_by_live_profile_evaluator"),
        fvg_16m_id=fvg_16m_id,
        fvg_12m_id=fvg_12m_id,
        fvg_8m_id="verified_by_live_profile_evaluator",
        entry_fvg_id=fvg_12m_id,
        stop_reference_price=Decimal(str(trade["stop_loss"])),
        final_target_price=Decimal(str(trade["take_profit"])),
        metadata={
            "latest_price": str(trade["entry_price"]),
            "entry_model": str(trade.get("entry_model") or "DIRECT_12M_RETRACE"),
            "strategy_profile": profile_id,
            "timeframe_profile": timeframe_profile_id,
            "selected_tp_model": selected_tp_model or str(trade.get("selected_tp_model") or ""),
            "applied_tp_model": selected_tp_model or str(trade.get("applied_tp_model") or ""),
            "time_exit_enabled": "YES" if selected_tp_model == "TIME_BASED_EXIT" else "NO",
            "time_exit_minutes": time_exit_minutes if selected_tp_model == "TIME_BASED_EXIT" else "",
            "planned_time_exit_at": (entry_time + timedelta(minutes=int(time_exit_minutes))).isoformat() if selected_tp_model == "TIME_BASED_EXIT" and time_exit_minutes else "",
            "time_exit_close_type": "MARKET",
            "live_trade_key": _trade_key(trade),
            "source": "LIVE_PROFILE_EVALUATOR",
            # Wall-clock moment this ENTRY_READY setup was created - NOT
            # entry_time/updated_at above (the trade's own entry candle
            # timestamp), and not created_at above either (the swing's
            # original detection timestamp when a tracked row exists for it -
            # see _find_tracked_setup_by_swing). live_automation.py's _process_setup logs the
            # real elapsed time between this and when it starts processing
            # the setup, to make the "detection and execution already run in
            # the same poll cycle" claim verifiable from real logs rather
            # than just code-reading.
            "detected_at_wallclock": datetime.now(timezone.utc).isoformat(),
        },
    )


def _apply_attempt_traces(
    state: Any,
    symbol: str,
    traces: object,
    *,
    profile_id: str,
    timeframe_profile_id: str,
    selected_tp_model: str,
    source: str,
) -> None:
    """Turn every Setup Radar attempt trace into a visible, tracked Setup row.

    Unlike _setup_from_trade (only ever called for a fresh, tradable ENTRY_READY
    candidate), this runs for every swing candidate the funnel walked this poll -
    active, invalidated, or completed - so the radar shows attempts in progress,
    not just trades. Each trace is applied independently so one malformed trace
    can never block the rest (same isolation pattern used elsewhere in this file).
    """
    if not isinstance(traces, (tuple, list)):
        return
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        try:
            _apply_one_attempt_trace(
                state,
                trace,
                profile_id=profile_id,
                timeframe_profile_id=timeframe_profile_id,
                selected_tp_model=selected_tp_model,
                source=source,
            )
        except Exception:
            logger.exception("Failed to apply one Setup Radar attempt trace for %s; continuing with remaining traces", symbol)


def _record_in_progress_before_terminal_move(
    state: Any,
    *,
    setup_id: str,
    symbol: str,
    direction: SetupDirection,
    created_at: datetime,
    current_state: SetupState,
    progress_percent: float,
    swing_16m_id: str | None = None,
    expansion_16m_id: str | None = None,
    fvg_16m_id: str | None = None,
    fvg_12m_id: str | None = None,
    fvg_8m_id: str | None = None,
    metadata: dict[str, str],
    now: datetime,
    source: str,
) -> None:
    """Guarantee a setup is recorded in IN PROGRESS (state.setups,
    state.setup_history) at its current stage before it is ever moved to
    COMPLETED or INVALIDATED - even one that resolves to ENTRY_READY or
    invalidates on the very first poll it is ever observed on, which would
    otherwise go straight into completed_setups/invalidated_setups without
    ever appearing in IN PROGRESS history at all.

    Only does real work for a setup_id with no history yet - a setup that
    has already been through at least one earlier poll has necessarily
    already passed through here (or through the normal existing-setup path
    in _apply_one_attempt_trace), so this is a no-op for it.
    """
    if setup_id in state.setup_history:
        return
    snapshot = Setup(
        setup_id=setup_id,
        symbol=symbol,
        direction=direction,
        current_state=current_state,
        progress_percent=progress_percent,
        status=SetupStatus.ACTIVE,
        created_at=created_at,
        updated_at=now,
        swing_16m_id=swing_16m_id,
        expansion_16m_id=expansion_16m_id,
        fvg_16m_id=fvg_16m_id,
        fvg_12m_id=fvg_12m_id,
        fvg_8m_id=fvg_8m_id,
        metadata=dict(metadata),
    )
    state.setups[setup_id] = snapshot
    state.setup_history[setup_id] = [
        {
            "from_state": None,
            "to_state": current_state.value,
            "changed_at": now.isoformat(),
            "reason": "recorded in IN PROGRESS before resolving in the same poll",
            "source": source,
        }
    ]


def _dwell_elapsed(*, symbol: str, setup_id: str, created_at: datetime, now: datetime, reason: str) -> bool:
    """Minimum IN PROGRESS dwell time: a non-execution exit to INVALIDATED
    (strategy failure or structural-match-only, here; the staleness gate has
    its own identical check in live_automation.py's _expire_if_stale) must
    wait at least MIN_DWELL_SECONDS since the setup's own created_at before
    it is allowed to actually happen - so the frontend (which polls every
    few seconds) gets a real chance to display the setup in IN PROGRESS
    first, instead of it being created and resolved within the same poll
    cycle and never visibly appearing at all. Does not apply to a hard
    execution decision (trade_opened/rejected/risk_blocked/no_margin) -
    those are never routed through here.

    Logs at DEBUG while still waiting, INFO the one time it actually clears.
    Returns True once dwell has elapsed (the caller should proceed with the
    move), False while still waiting (the caller must leave the setup
    exactly as it is - no field update, no re-evaluation recorded).
    """
    time_in_progress = (now - created_at).total_seconds()
    if time_in_progress < MIN_DWELL_SECONDS:
        logger.debug("[DWELL] %s %s waiting %.1fs / %ss before INVALIDATED (%s)", symbol, setup_id, time_in_progress, MIN_DWELL_SECONDS, reason)
        return False
    logger.info("[IN PROGRESS -> INVALIDATED] %s %s dwell complete, reason: %s", symbol, setup_id, reason)
    return True


def _apply_one_attempt_trace(
    state: Any,
    trace: dict[str, object],
    *,
    profile_id: str,
    timeframe_profile_id: str,
    selected_tp_model: str,
    source: str,
) -> None:
    direction = SetupDirection.BEARISH if str(trace.get("direction")).upper() == "BEARISH" else SetupDirection.BULLISH
    swing_timestamp = datetime.fromisoformat(str(trace["swing_timestamp"]).replace("Z", "+00:00"))
    swing_id = str(trace["swing_16m_id"])
    setup_id = build_setup_id(symbol=str(trace["symbol"]), direction=direction, created_at=swing_timestamp, htf_fvg_id=swing_id)

    # Fix 4 (Setup Radar journey): once a setup_id has ever resolved into
    # completed_setups or invalidated_setups, it is permanently done - the
    # live detection funnel re-derives the exact same trace for this swing
    # on every later poll for as long as it stays in the rolling candle
    # buffer, and must never recreate or re-toggle it. This is also what
    # keeps the append-only history lists stable between polls (Fix 2/3):
    # without it, a swing whose expansion/retrace check flips poll-to-poll
    # could un-invalidate and re-invalidate the same setup_id repeatedly,
    # which means removing and re-adding list entries instead of writing
    # each one exactly once, ever.
    if setup_id in state.resolved_setup_ids:
        return

    stage = str(trace.get("stage") or "SWING_16M_CONFIRMED")
    mapped_state_for_stage = _ATTEMPT_STAGE_TO_STATE.get(stage, SetupState.SWING_16M_CONFIRMED)
    target_state = mapped_state_for_stage
    strategy_failed = trace.get("invalidation_reason") is not None and bool(trace.get("is_terminal")) and stage != "ENTRY_READY"
    # Fix 2 (Setup Radar journey): the attempt-tracer is a diagnostic system
    # only - it is never wired into real execution. _setup_from_trade plus
    # live_automation.py's signal->risk->dry-run->live-order pipeline is the
    # only path that ever makes a real execution decision (trade_opened/
    # rejected/risk_blocked/no_margin - see should_leave_in_progress's
    # TERMINAL_EXECUTION_STATES). Reaching ENTRY_READY here only means the
    # funnel's structural conditions (swing/expansion/FVG/retrace) matched -
    # it is NOT an execution outcome, so it must never land in COMPLETED.
    # Classified as INVALIDATED instead, with a dedicated reason
    # (NO_EXECUTION_ATTEMPTED). If _setup_from_trade also finds this exact
    # swing (this poll or a later one), it reclaims this same setup_id
    # straight out of invalidated_setups exactly like it already does out of
    # completed_setups (see _find_tracked_setup_by_swing) - that reclaim path
    # is unaffected by this change.
    structural_match_only = stage == "ENTRY_READY"
    is_invalidated = strategy_failed or structural_match_only
    if is_invalidated:
        target_state = SetupState.INVALIDATED
        target_status = SetupStatus.INVALIDATED
    else:
        target_status = SetupStatus.ACTIVE
    now = datetime.now(timezone.utc)

    # existing can only ever be an IN PROGRESS row now - once resolved (and
    # therefore in resolved_setup_ids), the early return above already
    # skipped this trace entirely, so existing is never found carrying an
    # invalidation_reason here.
    existing = state.setups.get(setup_id)
    new_progress = max(existing.progress_percent if existing is not None else 0.0, float(trace.get("progress_percent") or 0.0))

    metadata = dict(existing.metadata) if existing is not None else {}
    metadata.update(
        {
            "strategy_profile": profile_id,
            "timeframe_profile": timeframe_profile_id,
            "selected_tp_model": selected_tp_model,
            "source": source,
            "swing_price": str(trace.get("swing_price") or ""),
            "retrace_candle_found": "YES" if trace.get("retrace_candle_found") else "NO",
        }
    )
    if trace.get("entry_price"):
        metadata["entry_signal_price"] = str(trace["entry_price"])

    field_updates: dict[str, object] = {
        "symbol": str(trace["symbol"]),
        "direction": direction,
        "current_state": target_state,
        "progress_percent": new_progress,
        "status": target_status,
        "updated_at": now,
        "completed_at": existing.completed_at if existing is not None else None,
        "swing_16m_id": swing_id,
        "expansion_16m_id": trace.get("expansion_16m_id") or (existing.expansion_16m_id if existing else None),
        "fvg_16m_id": trace.get("fvg_16m_id") or (existing.fvg_16m_id if existing else None),
        "fvg_12m_id": trace.get("fvg_12m_id") or (existing.fvg_12m_id if existing else None),
        "fvg_8m_id": trace.get("fvg_8m_id") or (existing.fvg_8m_id if existing else None),
        "stop_reference_price": trace.get("stop_loss") or (existing.stop_reference_price if existing else None),
        "final_target_price": trace.get("take_profit") or (existing.final_target_price if existing else None),
        "metadata": metadata,
    }
    if strategy_failed:
        field_updates["invalidated_at"] = now
        field_updates["invalidation_reason"] = InvalidationReason(str(trace["invalidation_reason"]))
        # trace["stage"] is never advanced past the last checkpoint that
        # actually passed (see _attempt_traces_for_direction) - it is never
        # reassigned to a failure marker - so it is exactly the last valid
        # stage reached before this trace's failing check ran.
        field_updates["last_valid_stage"] = stage
        field_updates["execution_status"] = "invalidated"
    elif structural_match_only:
        # Reached ENTRY_READY/100% structurally, but - unlike a real trade -
        # this diagnostic row never goes through execution, so completed_at
        # (the entry-tap timestamp) stays unset too: it represents "the
        # moment this setup's chain actually completed", and this one never
        # really did.
        field_updates["invalidated_at"] = now
        field_updates["invalidation_reason"] = InvalidationReason.NO_EXECUTION_ATTEMPTED
        field_updates["last_valid_stage"] = "ENTRY_READY"
        field_updates["execution_status"] = "invalidated"
    # No "favorable resolution" branch anymore: a setup_id that was ever
    # invalidated never reaches this point a second time (the
    # resolved_setup_ids check above already returned) - once invalidated,
    # permanently done, per the Setup Radar journey rule (Fix 4).

    if existing is None:
        # A setup that resolves immediately on the very first poll it is
        # ever observed on (terminal already on first sight) must still be
        # recorded in IN PROGRESS before moving on - otherwise it would go
        # straight into invalidated_setups/completed_setups and never once
        # appear in IN PROGRESS history.
        if structural_match_only:
            # Reached ENTRY_READY on the very first poll this swing was ever
            # observed on - still must be recorded at the last real stage
            # before ENTRY_READY (FVG_8M_CONFIRMED/80%), never at
            # mapped_state_for_stage (SetupState.COMPLETED for this stage),
            # which would be a terminal marker, not an IN PROGRESS one.
            _record_in_progress_before_terminal_move(
                state,
                setup_id=setup_id,
                symbol=str(trace["symbol"]),
                direction=direction,
                created_at=swing_timestamp,
                current_state=SetupState.FVG_8M_CONFIRMED,
                progress_percent=80.0,
                swing_16m_id=swing_id,
                expansion_16m_id=field_updates.get("expansion_16m_id"),
                fvg_16m_id=field_updates.get("fvg_16m_id"),
                fvg_12m_id=field_updates.get("fvg_12m_id"),
                fvg_8m_id=field_updates.get("fvg_8m_id"),
                metadata=metadata,
                now=now,
                source=source,
            )
        elif is_invalidated:  # strategy_failed
            _record_in_progress_before_terminal_move(
                state,
                setup_id=setup_id,
                symbol=str(trace["symbol"]),
                direction=direction,
                created_at=swing_timestamp,
                current_state=mapped_state_for_stage,
                progress_percent=new_progress,
                swing_16m_id=swing_id,
                expansion_16m_id=field_updates.get("expansion_16m_id"),
                fvg_16m_id=field_updates.get("fvg_16m_id"),
                fvg_12m_id=field_updates.get("fvg_12m_id"),
                fvg_8m_id=field_updates.get("fvg_8m_id"),
                metadata=metadata,
                now=now,
                source=source,
            )
        if is_invalidated and not _dwell_elapsed(symbol=str(trace["symbol"]), setup_id=setup_id, created_at=swing_timestamp, now=now, reason=field_updates["invalidation_reason"].value):
            # Not yet - the swing is already recorded in IN PROGRESS above
            # (at its pre-failure stage), but the move to INVALIDATED itself
            # waits for MIN_DWELL_SECONDS to elapse since swing_timestamp -
            # no strategy re-evaluation, nothing else happens here.
            return
        setup = Setup(
            setup_id=setup_id,
            created_at=swing_timestamp,
            state_history=(
                StateHistoryEntry(
                    from_state=None,
                    to_state=target_state,
                    changed_at=now,
                    reason=f"setup radar: {stage}",
                    triggering_object_type="Swing",
                    triggering_object_id=swing_id,
                ),
            ),
            **field_updates,
        )
        state.setup_history.setdefault(setup_id, []).append(
            {
                "from_state": None,
                "to_state": target_state.value,
                "changed_at": now.isoformat(),
                "reason": f"setup radar: {stage}",
                "source": source,
            }
        )
        _store_setup(state, setup, is_invalidated=is_invalidated, target_status=target_status)
        return

    if is_invalidated and not _dwell_elapsed(symbol=existing.symbol, setup_id=setup_id, created_at=existing.created_at, now=now, reason=field_updates["invalidation_reason"].value):
        # Not yet - leave existing exactly as it is: no field update, no
        # state_history append, no strategy re-evaluation recorded. The
        # funnel may keep re-deriving the same trace every poll until dwell
        # elapses, but nothing about the stored setup changes because of it.
        return

    if existing.current_state != target_state:
        state.setup_history.setdefault(setup_id, []).append(
            {
                "from_state": existing.current_state.value,
                "to_state": target_state.value,
                "changed_at": now.isoformat(),
                "reason": f"setup radar: {stage}",
                "source": source,
            }
        )
    _store_setup(state, replace(existing, **field_updates), is_invalidated=is_invalidated, target_status=target_status)


def _append_resolved_setup(state: Any, store: list[Any], setup: Any) -> None:
    """The one and only way a setup ever enters completed_setups or
    invalidated_setups (Fix 2/3 - Setup Radar journey): prepend to the front
    (index 0), then drop anything past MAX_TRACKED_SETUP_ATTEMPTS (the
    oldest, now at the end) - never re-sorted, never rebuilt, so the list is
    byte-for-byte identical between polls unless a new entry was just added
    right here. setup.setup_id is also added to state.resolved_setup_ids,
    permanently (never evicted, unlike the capped list itself) - see
    _apply_one_attempt_trace's check at the top, which is what stops the live
    detection funnel from recreating a setup_id that has already resolved
    once, even after it ages out of the visible, capped list.

    Setup Radar swing-level dedup (Fix 1): setup.created_at is always the
    swing's own original detection timestamp (the right-candle timestamp
    _attempt_traces_for_direction reports as swing_timestamp - see
    _apply_one_attempt_trace, and _setup_from_trade's tracked-row handoff),
    so the permanent swing dedup key (symbol + direction + that timestamp -
    see setup_models.build_swing_dedup_key) is derived from it and added to
    state.resolved_swing_keys in this exact same step - atomically with the
    COMPLETED/INVALIDATED write below, never after, never as a separate
    step. This is what is actually checked BEFORE the funnel ever runs for a
    swing (detect_live_setups_for_symbol's _filter_resolved_swings), which
    stops the swing from being re-evaluated at all on a later poll,
    regardless of what setup_id a fresh funnel run would otherwise mint for
    it.

    A no-op if setup_id has already resolved (defensive - by construction,
    every caller already checked this first, but a setup_id must never be
    written twice regardless).
    """
    if setup.setup_id in state.resolved_setup_ids:
        return
    store.insert(0, setup)
    del store[MAX_TRACKED_SETUP_ATTEMPTS:]
    state.resolved_setup_ids.add(setup.setup_id)
    state.resolved_swing_keys.add(build_swing_dedup_key(symbol=setup.symbol, direction=setup.direction, swing_timestamp=setup.created_at))


def _store_setup(state: Any, setup: Any, *, is_invalidated: bool, target_status: SetupStatus) -> None:
    """Route a setup to the one store matching its current status. A setup
    that resolves (invalidated or completed) leaves the uncapped in-progress
    pool and lands in its own append-only, capped-at-100 history - for good;
    there is no path back (see _append_resolved_setup / resolved_setup_ids).

    Fix 2/4 (Setup Radar swing-level dedup): for a resolving setup, the
    terminal store write (and its swing key, both inside
    _append_resolved_setup) happens FIRST, while the setup is still also
    sitting in state.setups - only once that has fully succeeded does it
    leave IN PROGRESS. This non-negotiable ordering means a setup is never
    silently dropped: it cannot exist in neither store, not even for the
    instant between two statements, so an exception raised mid-write can
    never lose it.
    """
    if is_invalidated:
        _append_resolved_setup(state, state.invalidated_setups, setup)
        save_setup_history_store(state)
        state.setups.pop(setup.setup_id, None)
    elif target_status is SetupStatus.COMPLETED:
        _append_resolved_setup(state, state.completed_setups, setup)
        save_setup_history_store(state)
        state.setups.pop(setup.setup_id, None)
    else:
        state.setups[setup.setup_id] = setup


def move_setup_to_completed(state: Any, setup: Any) -> None:
    """Move a real ENTRY_READY setup (_setup_from_trade) into completed_setups
    once live automation actually submits its order - called from
    live_automation.py's _process_setup. Its Setup Radar lifecycle is done at
    that point (it is now a live trade, visible on the Execution page via the
    matching Bitget order), so it leaves the uncapped in-progress pool the
    same way an attempt-trace COMPLETED row does.

    Fix 2/4 ordering (Setup Radar swing-level dedup): written into
    completed_setups (and its swing key) before being removed from
    state.setups - never the other way around, so a crash between the two
    statements can never leave this setup recorded nowhere.
    """
    _append_resolved_setup(state, state.completed_setups, setup)
    save_setup_history_store(state)
    state.setups.pop(setup.setup_id, None)


def expire_stale_setup(state: Any, setup: Any, *, expired_at: datetime) -> Any:
    """Move an ENTRY_READY setup that sat too long without being submitted
    (see _expire_if_stale in live_automation.py) into invalidated_setups as
    EXPIRED, instead of leaving it in the uncapped pool where a later poll
    could still submit an order against an entry zone the market has likely
    moved away from.

    invalidation_reason=SETUP_EXPIRED records the exact reason this setup
    left IN PROGRESS, per the Setup Radar journey's exit-path rule (Fix 1) -
    Setup._validate() now allows this specifically for current_state=EXPIRED
    (see setup_models.py), the one deliberate exception to "100%-complete
    setups never carry an invalidation_reason", since this setup legitimately
    did reach ENTRY_READY/100% before going stale.

    Fix 2 ordering (non-negotiable): written into invalidated_setups (and
    its swing key) and persisted to disk BEFORE being removed from
    state.setups - the setup must be recorded before it is removed, not
    after, not silently dropped.
    """
    expired = replace(
        setup,
        current_state=SetupState.EXPIRED,
        status=SetupStatus.EXPIRED,
        updated_at=expired_at,
        invalidated_at=expired_at,
        invalidation_reason=InvalidationReason.SETUP_EXPIRED,
        last_valid_stage="ENTRY_READY",
        execution_status="expired",
    )
    _append_resolved_setup(state, state.invalidated_setups, expired)
    save_setup_history_store(state)
    state.setups.pop(setup.setup_id, None)
    return expired


def _suppress_redundant_attempt_trace(state: Any, swing_16m_id: str | None) -> None:
    """Drop the attempt-tracer's own diagnostic row for a swing (INVALIDATED/
    NO_EXECUTION_ATTEMPTED, see _apply_one_attempt_trace's structural-match
    handling) once a real ENTRY_READY trade has been tracked for that same
    swing.

    _apply_one_attempt_trace and _setup_from_trade both derive from the
    exact same funnel evaluation for a given swing - one is a diagnostic
    "this chain reached ENTRY_READY structurally" marker, the other is the
    real, tradable setup. Without this, a single real-world completion shows
    as two rows in Setup Radar (same symbol, direction, near-identical
    timestamp, since both are produced moments apart within the same poll)
    which looks like a duplicate bug even though the two setup_ids are never
    actually equal. A narrow, documented exception to "append-only" (Fix
    2/3) - this removes a genuine duplicate of the same real-world event,
    not a poll-cycle reorder, and is normally a no-op now that
    _find_tracked_setup_by_swing lets the real trade take over the tracer
    row's own setup_id instead of minting a second one.
    """
    if not swing_16m_id:
        return
    for setup in list(state.completed_setups):
        if setup.swing_16m_id == swing_16m_id and setup.metadata.get("source") != "LIVE_PROFILE_EVALUATOR":
            state.completed_setups.remove(setup)
            state.setup_history.pop(setup.setup_id, None)
            state.resolved_setup_ids.discard(setup.setup_id)
    for setup in list(state.invalidated_setups):
        if setup.swing_16m_id == swing_16m_id and setup.invalidation_reason is InvalidationReason.NO_EXECUTION_ATTEMPTED and setup.metadata.get("source") != "LIVE_PROFILE_EVALUATOR":
            state.invalidated_setups.remove(setup)
            state.setup_history.pop(setup.setup_id, None)
            state.resolved_setup_ids.discard(setup.setup_id)


def _fresh_trade_candidate(trades: object, candles: tuple[Candle, ...], detector_state: dict[str, Any]) -> dict[str, object] | None:
    """The most recently-confirmed trade candidate that has never been
    processed before.

    "Fresh" here means "discovered for the first time this poll" - not
    "its own entry candle is chronologically the latest 1m candle", which is
    what this used to require. That requirement made a candidate's entry
    timestamp equal to candles[-1]/candles[-2] - but the shared strategy
    funnel only confirms ENTRY_READY once the *entire* retrace window
    (profile.retrace_window_8m_candles worth of 8M candles) has fully
    elapsed since the 16M FVG confirmed, and then searches that window
    front-to-back for the first qualifying retrace+tap. The tap that
    satisfies entry is therefore very often found near the START of an
    already-elapsed window, not its end - meaning a structurally valid,
    freshly-confirmed completion was being discovered "too old" by this
    measure on virtually every occurrence, restart/outage or not.
    _trade_key/processed_trade_keys already guarantee a given trade is only
    ever picked up once - that is the freshness signal that actually applies
    here, not chronological age of the entry candle.
    """
    if not isinstance(trades, (tuple, list)) or not candles:
        return None
    seen = set(str(key) for key in detector_state.get("processed_trade_keys", []))
    for trade in reversed([trade for trade in trades if isinstance(trade, dict)]):
        if str(trade.get("outcome")) == "RISK_REJECTED":
            continue
        if _trade_key(trade) in seen:
            continue
        if "entry_timestamp" not in trade:
            continue
        return trade
    return None


def _stale_trade_candidates(
    trades: object,
    candles: tuple[Candle, ...],
    detector_state: dict[str, Any],
    *,
    exclude: dict[str, object] | None = None,
) -> tuple[dict[str, object], ...]:
    """Diagnostics only - never changes what gets traded.

    Other never-seen trade candidates the shared strategy funnel found this
    same poll, besides the single one `_fresh_trade_candidate` already
    picked (passed as `exclude`). This only has entries when more than one
    swing resolves to ENTRY_READY in the very same poll - typically a
    restart/outage backlog surfacing at once. Each one will still be picked
    up and acted on automatically, one per poll, on a later pass; this is
    purely visibility into "more than one showed up at once", not a list of
    things that will never be traded.

    Each returned trade dict carries two added keys describing how old the
    entry candle already was relative to the latest live candle when found:
    candles_past_window (0 means right at the latest/second-latest candle,
    1 means one candle further gone, etc.) and seconds_past_window
    (candles_past_window * 60).
    """
    if not isinstance(trades, (tuple, list)) or not candles:
        return ()
    latest = candles[-1].timestamp
    latest_allowed = {latest, candles[-2].timestamp if len(candles) > 1 else latest}
    seen = set(str(key) for key in detector_state.get("processed_trade_keys", []))
    exclude_key = _trade_key(exclude) if exclude is not None else None
    stale: list[dict[str, object]] = []
    for trade in trades:
        if not isinstance(trade, dict) or str(trade.get("outcome")) == "RISK_REJECTED":
            continue
        if _trade_key(trade) in seen:
            continue
        if exclude_key is not None and _trade_key(trade) == exclude_key:
            continue
        try:
            entry_time = datetime.fromisoformat(str(trade["entry_timestamp"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if entry_time not in latest_allowed:
            candles_after_entry = sum(1 for candle in candles if candle.timestamp > entry_time)
            candles_past_window = max(0, candles_after_entry - 1)
            stale.append({**trade, "candles_past_window": candles_past_window, "seconds_past_window": candles_past_window * 60})
    return tuple(stale)


def _record_stale_skip(symbol: str, stale: tuple[dict[str, object], ...], detector_state: dict[str, Any]) -> None:
    timestamps = sorted(str(trade.get("entry_timestamp") or "") for trade in stale)
    detector_state["stale_trade_candidates_skipped_total"] = int(detector_state.get("stale_trade_candidates_skipped_total") or 0) + len(stale)
    detector_state["last_stale_skip"] = {
        "symbol": symbol,
        "count": len(stale),
        "oldest_entry_timestamp": timestamps[0],
        "newest_entry_timestamp": timestamps[-1],
        "detected_at": _now(),
    }
    logger.warning(
        "Live detection for %s found %s additional never-seen trade candidate(s) via the shared strategy funnel "
        "this same poll, beyond the one just picked up - entry_timestamp range %s..%s. These are queued, not "
        "dropped: each will still be picked up automatically, one per poll, on a later pass. More than one at "
        "once usually means a monitoring gap (restart/outage) let several swings resolve before detection caught "
        "up, rather than something wrong with any individual candidate.",
        symbol,
        len(stale),
        timestamps[0],
        timestamps[-1],
    )


def _record_stale_skips_for_radar(state: Any, stale: tuple[dict[str, object], ...]) -> None:
    """Per-swing version of _record_stale_skip, for Setup Radar.

    _record_stale_skip only keeps the single latest skip event for a symbol
    (overwritten every poll), which is enough for a log line but not enough
    for radar_record() to say "this specific COMPLETED row was the one that
    got skipped." Keyed by swing_16m_id - the same id _apply_one_attempt_trace
    puts on the matching attempt-trace Setup row - so the two can be joined.

    Each record also says how long after the *current* monitoring session
    started this skip was detected, and whether that's within
    RESTART_CATCHUP_WINDOW_SECONDS - distinguishing "still catching up on a
    backlog right after a restart/outage" from "happened well into an
    otherwise-continuous session", without requiring a separate catch-up
    code path: the funnel already re-walks the full candidate-swing window
    on every poll, so anything missed during a gap surfaces here naturally
    the first time a poll runs after monitoring resumes.
    """
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    monitoring = getattr(state, "monitoring", None) or {}
    seconds_since_monitoring_started = None
    started_at_raw = monitoring.get("started_at") if isinstance(monitoring, dict) else None
    if started_at_raw and started_at_raw != "None":
        try:
            started_at = datetime.fromisoformat(str(started_at_raw).replace("Z", "+00:00"))
            seconds_since_monitoring_started = (now_dt - started_at).total_seconds()
        except ValueError:
            seconds_since_monitoring_started = None
    likely_restart_related = seconds_since_monitoring_started is not None and seconds_since_monitoring_started <= RESTART_CATCHUP_WINDOW_SECONDS
    for trade in stale:
        swing_id = str(trade.get("source_16m_swing_id") or "")
        if not swing_id:
            continue
        state.stale_trade_skips[swing_id] = {
            "swing_16m_id": swing_id,
            "symbol": str(trade.get("symbol") or ""),
            "direction": str(trade.get("direction") or ""),
            "entry_timestamp": str(trade.get("entry_timestamp") or ""),
            "candles_past_window": int(trade.get("candles_past_window") or 0),
            "seconds_past_window": int(trade.get("seconds_past_window") or 0),
            "skipped_at": now,
            "seconds_since_monitoring_started": seconds_since_monitoring_started,
            "likely_restart_related": likely_restart_related,
        }
    _evict_oldest_stale_skips(state)


def _evict_oldest_stale_skips(state: Any, *, max_count: int = MAX_TRACKED_SETUP_ATTEMPTS) -> None:
    overflow = len(state.stale_trade_skips) - max_count
    if overflow <= 0:
        return
    oldest_first = sorted(state.stale_trade_skips.items(), key=lambda item: item[1].get("skipped_at") or "")
    for swing_id, _ in oldest_first[:overflow]:
        state.stale_trade_skips.pop(swing_id, None)


def _trade_key(trade: dict[str, object]) -> str:
    return "|".join(
        (
            str(trade.get("symbol", "")).upper(),
            str(trade.get("selected_strategy_profile") or trade.get("profile_id") or ""),
            str(trade.get("entry_timestamp") or ""),
            str(trade.get("source_12m_fvg_id") or trade.get("12m_fvg_id") or ""),
        )
    )


def _compact_funnel(funnel: dict[str, object], *, direction: str = "BEARISH") -> dict[str, object]:
    keys = ("candidate_16m_swing_highs", "passed_expansion", "passed_retrace", "entry_ready", "trades", "risk_rejected_count")
    compact = {key: funnel.get(key) for key in keys if key in funnel}
    if direction == "BULLISH" and "candidate_16m_swing_highs" in compact:
        compact["candidate_16m_swing_lows"] = compact.pop("candidate_16m_swing_highs")
    return compact


def _log_retrace_diagnostics(symbol: str, funnel: dict[str, Any], *, direction: str = "BEARISH") -> None:
    """Log which funnel stage absorbed expansion-passed candidates whenever
    none of them reach a fresh trade candidate. The compact funnel kept on
    detector_state drops the per-stage FVG counts (and, for non-default
    timeframe profiles, backtest_csv.py's own result dict already strips the
    16m/12m/8m-labeled keys before returning - see _build_strategy_funnel's
    timeframe_profile.profile_id != DEFAULT_16_12_8.profile_id branch), so
    this is otherwise impossible to see outside ad-hoc scripting."""
    passed_expansion = int(funnel.get("passed_expansion") or 0)
    passed_retrace = int(funnel.get("passed_retrace") or 0)
    if passed_expansion == 0 or passed_retrace > 0:
        return
    logger.info(
        "Live retrace diagnostics for %s (%s): passed_expansion=%s -> passed_main_fvg=%s -> passed_retrace_fvg=%s -> "
        "passed_internal_fvg=%s -> passed_retrace=%s (retrace_window_expired=%s, close_through_fvg_before_entry=%s)",
        symbol,
        direction,
        passed_expansion,
        funnel.get("passed_main_fvg_timeframe_fvg", funnel.get("passed_16m_fvg")),
        funnel.get("passed_retrace_fvg_timeframe_fvg", funnel.get("passed_12m_fvg")),
        funnel.get("passed_internal_fvg_timeframe_fvg", funnel.get("passed_8m_fvg")),
        passed_retrace,
        funnel.get("rejected_retrace_window_expired"),
        funnel.get("rejected_close_above_12m_fvg_before_entry") or funnel.get("rejected_close_above_12m_fvg"),
    )


def _finish(detector_state: dict[str, Any], status: str, reason: str, *, source: str) -> dict[str, Any]:
    detector_state["last_status"] = status
    detector_state["last_blocked_reason"] = "None" if status == "SETUP_CREATED" else reason
    return {"source": source, "status": status, "reason": reason, "created_at": _now()}


def _runner() -> ModuleType:
    global _RUNNER
    if _RUNNER is not None:
        return _RUNNER
    spec = importlib.util.spec_from_file_location("arjiobot_live_backtest_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load backtest runner from {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _RUNNER = module
    return module


def _parse_bitget_timestamp(value: str) -> datetime:
    try:
        numeric = int(value)
    except ValueError:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if numeric > 10_000_000_000:
        return datetime.fromtimestamp(numeric / 1000, tz=timezone.utc)
    return datetime.fromtimestamp(numeric, tz=timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
