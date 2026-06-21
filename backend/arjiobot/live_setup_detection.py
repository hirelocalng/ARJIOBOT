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
from arjiobot.setup_tracker.setup_models import (
    InvalidationReason,
    Setup,
    SetupDirection,
    SetupState,
    SetupStatus,
    StateHistoryEntry,
    build_setup_id,
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

# Setup Radar attempt stage -> SetupState. A trace reaching "ENTRY_READY" maps to
# COMPLETED rather than SetupState.ENTRY_READY: the actual automation-triggering
# ENTRY_READY row is created separately by the existing, untouched
# _setup_from_trade/_fresh_trade_candidate flow below (which carries the
# RR/TP-model-aware stop/target the risk engine actually needs). If a trace-derived
# row also became ENTRY_READY, run_live_automation_once's `current_state is
# ENTRY_READY` filter could see two rows for the same opportunity and submit twice.
_ATTEMPT_STAGE_TO_STATE = {
    "SWING_16M_CONFIRMED": SetupState.SWING_16M_CONFIRMED,
    "EXPANSION_16M_CONFIRMED": SetupState.EXPANSION_16M_CONFIRMED,
    "FVG_16M_CONFIRMED": SetupState.FVG_16M_CONFIRMED,
    "FVG_12M_CONFIRMED": SetupState.FVG_12M_CONFIRMED,
    "FVG_8M_CONFIRMED": SetupState.FVG_8M_CONFIRMED,
    "ENTRY_READY": SetupState.COMPLETED,
}


def live_setup_detection_status(state: Any) -> dict[str, Any]:
    return dict(state.live_setup_detection)


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
        selected_tp_model = str(state.settings.get("selected_rr_profile") or profile.tp_model).upper()
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
        runner = _runner()
        required_minutes = runner._required_timeframes(timeframe_profile)
        profiles = {minutes: build_timeframe_profile(candles, minutes) for minutes in required_minutes}
        if not profiles.get(timeframe_profile.swing_timeframe) or not profiles.get(1):
            return _finish(detector_state, "WAITING", "not enough aligned candles for selected timeframe profile", source=source)

        swing_results = SwingDetectionEngine().detect_all_swings(profiles[timeframe_profile.swing_timeframe])
        bearish_swing_highs = [swing for swing in swing_results.swing_highs if swing.swing_type is SwingType.HIGH]
        bullish_swing_lows = [swing for swing in swing_results.swing_lows if swing.swing_type is SwingType.LOW]
        expansions_main = runner._research_expansions(swing_results.all_swings)
        fvg_results = {
            minutes: FVGDetectionEngine().detect_fvgs(
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
            selected_rr_profile=profile.tp_model if selected_tp_model == "TIME_BASED_EXIT" else str(state.settings.get("selected_rr_profile") or "RR_1_5"),
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
                stale = _stale_trade_candidates(funnel.get("trade_list", ()), candles, detector_state)
                if stale:
                    _record_stale_skip(symbol, stale, detector_state)
                    _record_stale_skips_for_radar(state, stale)
                waiting_reasons.append(f"{direction}: no fresh live trade candidate found")
                continue

            setup = _setup_from_trade(
                fresh,
                profile_id=profile.profile_id,
                timeframe_profile_id=timeframe_profile.profile_id,
                selected_tp_model=selected_tp_model,
                time_exit_minutes=str(state.settings.get("time_exit_minutes") or "30"),
            )
            if setup.setup_id not in state.setups:
                state.setups[setup.setup_id] = setup
                state.setup_history[setup.setup_id] = [
                    {
                        "from_state": None,
                        "to_state": SetupState.ENTRY_READY.value,
                        "changed_at": setup.updated_at.isoformat(),
                        "reason": "live profile evaluator created entry-ready setup",
                        "source": source,
                    }
                ]
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


def _setup_from_trade(trade: dict[str, object], *, profile_id: str, timeframe_profile_id: str, selected_tp_model: str = "", time_exit_minutes: str = "") -> Setup:
    entry_time = datetime.fromisoformat(str(trade["entry_timestamp"]).replace("Z", "+00:00"))
    direction = SetupDirection.BEARISH if str(trade.get("direction", "BEARISH")).upper() == "BEARISH" else SetupDirection.BULLISH
    setup_id = build_setup_id(
        symbol=str(trade["symbol"]),
        direction=direction,
        created_at=entry_time,
        htf_fvg_id=str(trade.get("source_16m_fvg_id") or trade.get("source_12m_fvg_id") or ""),
    )
    snapshot = trade.get("setup_snapshot") if isinstance(trade.get("setup_snapshot"), dict) else {}
    expansion = snapshot.get("expansion") if isinstance(snapshot.get("expansion"), dict) else {}
    return Setup(
        setup_id=setup_id,
        symbol=str(trade["symbol"]),
        direction=direction,
        current_state=SetupState.ENTRY_READY,
        progress_percent=100.0,
        status=SetupStatus.ENTRY_READY,
        created_at=entry_time,
        updated_at=entry_time,
        htf_fvg_id=str(trade.get("source_16m_fvg_id") or trade.get("source_12m_fvg_id") or ""),
        swing_16m_id=str(trade.get("source_16m_swing_id") or ""),
        expansion_16m_id=str(expansion.get("expansion_id") or "verified_by_live_profile_evaluator"),
        fvg_16m_id=str(trade.get("source_16m_fvg_id") or ""),
        fvg_12m_id=str(trade.get("source_12m_fvg_id") or trade.get("12m_fvg_id") or ""),
        fvg_8m_id="verified_by_live_profile_evaluator",
        entry_fvg_id=str(trade.get("source_12m_fvg_id") or trade.get("12m_fvg_id") or ""),
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
            # entry_time/created_at above, which is the trade's own entry
            # candle timestamp. live_automation.py's _process_setup logs the
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

    stage = str(trace.get("stage") or "SWING_16M_CONFIRMED")
    target_state = _ATTEMPT_STAGE_TO_STATE.get(stage, SetupState.SWING_16M_CONFIRMED)
    is_invalidated = trace.get("invalidation_reason") is not None and bool(trace.get("is_terminal")) and stage != "ENTRY_READY"
    if is_invalidated:
        target_state = SetupState.INVALIDATED
        target_status = SetupStatus.INVALIDATED
    elif stage == "ENTRY_READY":
        target_status = SetupStatus.COMPLETED
    else:
        target_status = SetupStatus.ACTIVE
    now = datetime.now(timezone.utc)

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
        "swing_16m_id": swing_id,
        "expansion_16m_id": trace.get("expansion_16m_id") or (existing.expansion_16m_id if existing else None),
        "fvg_16m_id": trace.get("fvg_16m_id") or (existing.fvg_16m_id if existing else None),
        "fvg_12m_id": trace.get("fvg_12m_id") or (existing.fvg_12m_id if existing else None),
        "fvg_8m_id": trace.get("fvg_8m_id") or (existing.fvg_8m_id if existing else None),
        "stop_reference_price": trace.get("stop_loss") or (existing.stop_reference_price if existing else None),
        "final_target_price": trace.get("take_profit") or (existing.final_target_price if existing else None),
        "metadata": metadata,
    }
    if is_invalidated:
        field_updates["invalidated_at"] = now
        field_updates["invalidation_reason"] = InvalidationReason(str(trace["invalidation_reason"]))
    elif existing is not None and existing.invalidation_reason is not None:
        # A swing whose expansion/FVG check failed on an earlier poll can still
        # resolve favorably on a later one once more candles arrive (e.g. an
        # expansion that takes more bars to confirm) - replace() only overrides
        # the keys listed here, so without this the setup's stale INVALIDATED
        # reason/timestamp would survive onto its new ACTIVE/COMPLETED row and
        # the radar would show a "100% complete" or "still active" attempt that
        # also displays an old invalidation reason.
        field_updates["invalidated_at"] = None
        field_updates["invalidation_reason"] = None

    if existing is None:
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
        state.setups[setup_id] = setup
        state.setup_history[setup_id] = [
            {
                "from_state": None,
                "to_state": target_state.value,
                "changed_at": now.isoformat(),
                "reason": f"setup radar: {stage}",
                "source": source,
            }
        ]
        _evict_oldest_setup_attempts(state)
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
    state.setups[setup_id] = replace(existing, **field_updates)


def _evict_oldest_setup_attempts(state: Any, *, max_count: int = MAX_TRACKED_SETUP_ATTEMPTS) -> None:
    """Keep only the latest MAX_TRACKED_SETUP_ATTEMPTS rows, oldest evicted first.

    A setup pending live execution (status ENTRY_READY) is never evicted, so a
    burst of new attempts can never push out a trade automation hasn't acted on yet.
    """
    overflow = len(state.setups) - max_count
    if overflow <= 0:
        return
    evictable = sorted(
        (setup for setup in state.setups.values() if setup.status is not SetupStatus.ENTRY_READY),
        key=lambda setup: setup.created_at,
    )
    for setup in evictable[:overflow]:
        state.setups.pop(setup.setup_id, None)
        state.setup_history.pop(setup.setup_id, None)


def _fresh_trade_candidate(trades: object, candles: tuple[Candle, ...], detector_state: dict[str, Any]) -> dict[str, object] | None:
    if not isinstance(trades, (tuple, list)) or not candles:
        return None
    latest = candles[-1].timestamp
    latest_allowed = {latest, candles[-2].timestamp if len(candles) > 1 else latest}
    seen = set(str(key) for key in detector_state.get("processed_trade_keys", []))
    for trade in reversed([trade for trade in trades if isinstance(trade, dict)]):
        if str(trade.get("outcome")) == "RISK_REJECTED":
            continue
        if _trade_key(trade) in seen:
            continue
        try:
            entry_time = datetime.fromisoformat(str(trade["entry_timestamp"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if entry_time in latest_allowed:
            return trade
    return None


def _stale_trade_candidates(trades: object, candles: tuple[Candle, ...], detector_state: dict[str, Any]) -> tuple[dict[str, object], ...]:
    """Diagnostics only - never changes what gets traded.

    Trade candidates the shared strategy funnel (the same code path the
    backtest engine uses) found and that have not already been processed,
    but whose entry candle has rolled outside `_fresh_trade_candidate`'s
    freshness window. These are real, valid setups by the strategy's own
    logic; they are skipped purely because nothing polled closely enough to
    catch them in time - typically after a monitoring restart/outage backfills
    many candles at once. Surfacing them lets a gap be noticed instead of
    looking identical to "no setup formed."

    Each returned trade dict carries two added keys describing exactly how
    stale it is, relative to _fresh_trade_candidate's "latest or
    second-latest 1m candle" window: candles_past_window (0 means right at
    the edge of the window, 1 means one candle further gone, etc.) and
    seconds_past_window (candles_past_window * 60).
    """
    if not isinstance(trades, (tuple, list)) or not candles:
        return ()
    latest = candles[-1].timestamp
    latest_allowed = {latest, candles[-2].timestamp if len(candles) > 1 else latest}
    seen = set(str(key) for key in detector_state.get("processed_trade_keys", []))
    stale: list[dict[str, object]] = []
    for trade in trades:
        if not isinstance(trade, dict) or str(trade.get("outcome")) == "RISK_REJECTED":
            continue
        if _trade_key(trade) in seen:
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
        "Live detection for %s found %s valid trade candidate(s) via the shared strategy funnel that are no longer "
        "fresh (entry_timestamp older than the newest 1-2 live candles) and will NOT be acted on - entry_timestamp "
        "range %s..%s. This usually indicates a monitoring gap (restart/outage) let live candles get ahead of "
        "detection before the next poll caught up.",
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
