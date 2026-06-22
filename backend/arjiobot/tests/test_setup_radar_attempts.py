"""Tests for the Setup Radar live attempt tracker.

These prove the radar is a real setup-attempt tracker, not just an ENTRY_READY
trade log: every swing candidate becomes a visible, symbol-tagged attempt that
progresses or is invalidated through the chain, capped at the latest 100.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.backtesting.historical_replay import load_ohlcv_csv
from arjiobot.exchange.bitget_environment import BitgetCredentialConfig, TradeMode
from arjiobot.live_automation import run_live_automation_once
from arjiobot.live_setup_detection import (
    RESTART_CATCHUP_WINDOW_SECONDS,
    _apply_attempt_traces,
    _fresh_trade_candidate,
    _record_stale_skips_for_radar,
    _setup_from_trade,
    _stale_trade_candidates,
    _suppress_redundant_attempt_trace,
    _trade_key,
    detect_live_setups_for_symbol,
)
from arjiobot.market_data.candle_models import Candle, Timeframe
from arjiobot.setup_tracker.setup_models import InvalidationReason, SetupState, SetupStatus

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _fake_state(symbol: str, candles) -> SimpleNamespace:
    return SimpleNamespace(
        live_candles={symbol: candles},
        settings={
            "active_strategy_profile": "PROFILE_2",
            "starting_balance": "10000",
            "risk_amount_per_trade": "10",
            "max_leverage": "20",
        },
        setups={},
        invalidated_setups={},
        completed_setups={},
        setup_history={},
        stale_trade_skips={},
        live_setup_detection={"processed_trade_keys": []},
        live_fvg_engines={},
    )


def _all_tracked(state) -> list:
    """Every setup across all three stores - mirrors radar.py's _all_setups."""
    return [*state.setups.values(), *state.invalidated_setups.values(), *state.completed_setups.values()]


def test_swing_only_attempt_is_logged_and_visible_with_its_symbol() -> None:
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])

    detect_live_setups_for_symbol(state, "ADAUSDT")

    tracked = _all_tracked(state)
    assert tracked, "expected at least one tracked setup attempt"
    # Critical display requirement: every attempt, at every stage, carries its symbol.
    assert all(setup.symbol == "ADAUSDT" for setup in tracked)
    assert any(setup.swing_16m_id for setup in tracked)
    # At minimum, attempts should exist at or beyond the swing stage (20%).
    assert all(setup.progress_percent >= 20.0 for setup in tracked)


def test_failed_expansion_attempt_is_retained_with_invalidation_reason() -> None:
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])

    detect_live_setups_for_symbol(state, "ADAUSDT")

    # A failed/invalidated attempt now lives in invalidated_setups, not setups.
    expansion_failures = [
        setup
        for setup in state.invalidated_setups.values()
        if setup.invalidation_reason is InvalidationReason.EXPANSION_NOT_CONFIRMED
    ]
    assert expansion_failures, "expected at least one swing whose expansion never confirmed"
    failed = expansion_failures[0]
    assert failed.symbol == "ADAUSDT"
    assert failed.current_state is SetupState.INVALIDATED
    assert failed.status is SetupStatus.INVALIDATED
    # Highest progress reached (the swing stage) must be preserved, not reset to 0.
    assert failed.progress_percent == 20.0
    assert failed.invalidated_at is not None


def test_entry_ready_setup_from_trade_still_reaches_100_percent() -> None:
    """_setup_from_trade (the existing, untouched entry-ready path live automation
    depends on) must still produce a full-progress ENTRY_READY setup - the new
    attempt-trace tracking is additive and must not change this."""
    trade = {
        "trade_id": "trade_live_1",
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": "2026-06-16T01:30:00+00:00",
        "entry_price": "100",
        "stop_loss": "120",
        "take_profit": "80",
        "source_12m_fvg_id": "fvg12_live",
        "source_16m_swing_id": "swing16_live",
        "source_16m_fvg_id": "fvg16_live",
        "setup_snapshot": {"expansion": {"expansion_id": "exp16_live"}},
    }

    setup = _setup_from_trade(trade, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")

    assert setup.symbol == "ADAUSDT"
    assert setup.progress_percent == 100.0
    assert setup.current_state is SetupState.ENTRY_READY
    assert setup.status is SetupStatus.ENTRY_READY


def _swing_trace(swing_id: str, *, stage: str, progress_percent: float, invalidation_reason: str | None = None, is_terminal: bool = False) -> dict[str, object]:
    return {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "swing_16m_id": swing_id,
        "swing_timestamp": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=int(swing_id.split("_")[-1]))).isoformat(),
        "swing_price": "100",
        "expansion_16m_id": None,
        "fvg_16m_id": None,
        "fvg_12m_id": None,
        "fvg_8m_id": None,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "stage": stage,
        "progress_percent": progress_percent,
        "invalidation_reason": invalidation_reason,
        "is_terminal": is_terminal,
    }


def test_invalidated_history_is_capped_at_100_independently_of_in_progress() -> None:
    """invalidated_setups must keep only the latest 100, oldest evicted first -
    and must not be affected by how many in-progress setups exist, since they
    are now two entirely separate stores (see _store_setup)."""
    state = _fake_state("ADAUSDT", ())
    traces = tuple(
        _swing_trace(f"swing_inv_{i}", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
        for i in range(105)
    )
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert len(state.invalidated_setups) == 100
    assert state.setups == {}, "invalidated setups must never land in the in-progress store"
    # Oldest 5 (swing_inv_0..4) were evicted; the most recent must survive.
    remaining_ids = {setup.swing_16m_id for setup in state.invalidated_setups.values()}
    assert "swing_inv_104" in remaining_ids
    assert "swing_inv_0" not in remaining_ids


def test_completed_history_is_capped_at_100_independently_of_in_progress() -> None:
    state = _fake_state("ADAUSDT", ())
    traces = tuple(_swing_trace(f"swing_done_{i}", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True) for i in range(105))
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert len(state.completed_setups) == 100
    assert state.setups == {}, "completed setups must never land in the in-progress store"
    remaining_ids = {setup.swing_16m_id for setup in state.completed_setups.values()}
    assert "swing_done_104" in remaining_ids
    assert "swing_done_0" not in remaining_ids


def test_in_progress_pool_has_no_cap() -> None:
    """IN PROGRESS is explicitly uncapped per the Setup Radar spec - unlike
    invalidated/completed, it must hold every currently-active attempt with
    no eviction at all, however many there are."""
    state = _fake_state("ADAUSDT", ())
    traces = tuple(_swing_trace(f"swing_active_{i}", stage="SWING_16M_CONFIRMED", progress_percent=20.0) for i in range(150))
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert len(state.setups) == 150
    assert state.invalidated_setups == {}
    assert state.completed_setups == {}


def test_eviction_never_removes_a_pending_entry_ready_setup() -> None:
    """A real ENTRY_READY setup (_setup_from_trade) stays in the uncapped
    in-progress pool, untouched by completed_setups/invalidated_setups
    filling up around it - it only ever leaves once live automation actually
    submits an order for it (move_setup_to_completed)."""
    state = _fake_state("ADAUSDT", ())
    pending_trade = {
        "trade_id": "trade_pending_1",
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": "2026-06-16T01:30:00+00:00",
        "entry_price": "100",
        "stop_loss": "120",
        "take_profit": "80",
        "source_12m_fvg_id": "fvg12_pending",
        "source_16m_swing_id": "swing16_pending",
        "source_16m_fvg_id": "fvg16_pending",
    }
    pending = _setup_from_trade(pending_trade, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state.setups[pending.setup_id] = pending

    traces = tuple(_swing_trace(f"swing_flood_{i}", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True) for i in range(105))
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert pending.setup_id in state.setups, "a pending ENTRY_READY setup must never be evicted"
    assert state.setups[pending.setup_id].status is SetupStatus.ENTRY_READY
    assert len(state.completed_setups) == 100, "the flood of unrelated completions must still respect its own cap"


def test_invalidation_reason_clears_when_a_later_poll_resolves_favorably() -> None:
    """A swing that fails on one poll (e.g. expansion not confirmed yet) but
    resolves favorably on a later poll (more candles arrived) must not keep
    displaying its old invalidation reason once it is ACTIVE/COMPLETED again -
    that stale combination ("100% complete" or "still active" next to a leftover
    invalidation reason) is the literal Setup Radar bug being fixed here."""
    state = _fake_state("ADAUSDT", ())
    base_trace = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "swing_16m_id": "swing_1",
        "swing_timestamp": "2026-06-16T01:00:00+00:00",
        "swing_price": "100",
        "expansion_16m_id": None,
        "fvg_16m_id": None,
        "fvg_12m_id": None,
        "fvg_8m_id": None,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
    }
    failed_trace = {**base_trace, "stage": "SWING_16M_CONFIRMED", "progress_percent": 20.0, "invalidation_reason": "EXPANSION_NOT_CONFIRMED", "is_terminal": True}

    _apply_attempt_traces(state, "ADAUSDT", (failed_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="LIVE_MARKET_DATA")
    [setup] = state.invalidated_setups.values()
    assert setup.status is SetupStatus.INVALIDATED
    assert setup.invalidation_reason is InvalidationReason.EXPANSION_NOT_CONFIRMED
    assert setup.invalidated_at is not None
    assert state.setups == {}

    resolved_trace = {**base_trace, "stage": "ENTRY_READY", "progress_percent": 100.0, "invalidation_reason": None, "is_terminal": True}
    _apply_attempt_traces(state, "ADAUSDT", (resolved_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="LIVE_MARKET_DATA")
    assert state.invalidated_setups == {}, "must move out of invalidated_setups once it resolves favorably"
    [setup] = state.completed_setups.values()
    assert setup.progress_percent == 100.0
    assert setup.status is SetupStatus.COMPLETED
    assert setup.invalidation_reason is None, "stale invalidation reason must not survive onto a resolved attempt"
    assert setup.invalidated_at is None


def test_live_automation_only_acts_on_entry_ready_setups() -> None:
    """Attempt-trace-derived rows (ACTIVE/INVALIDATED/COMPLETED) must never be
    picked up by run_live_automation_once - only a real ENTRY_READY setup from
    the existing, untouched trade-detection flow can trigger dry-run/submission.

    Uses the same fully-armed live state as test_live_automation_routes.py so
    preflight passes and the ENTRY_READY filter itself is what's exercised.
    Uses synthetic attempt traces (_apply_attempt_traces), not a real CSV
    detection window, to guarantee no real ENTRY_READY trade exists alongside
    them - a real strategy evaluation window almost always produces one
    quickly once a genuinely fresh signal is no longer discarded as stale
    (see _fresh_trade_candidate), which is the correct, fixed behavior, not
    something this filter test should depend on being absent.
    """
    api = client()
    state = get_state()
    service = state.bitget_environment
    service.runtime_credentials = BitgetCredentialConfig(api_key="key", api_secret="secret", passphrase="pass")
    service.mode = TradeMode.LIVE
    service.live_armed = True
    service.last_connection_result = {
        "connection_status": "PASSED",
        "available_balance": "1000",
        "available_margin": "1000",
        "last_successful_verification_time": "2026-06-16T00:00:00+00:00",
    }
    state.settings.update(
        {
            "adapter_mode": "BITGET_LIVE",
            "live_trading_enabled": True,
            "trading_mode": "LIVE",
        }
    )
    state.monitoring.update({"active": True, "session_id": "test", "source": "LIVE_MARKET_DATA"})
    state.market_polls["ADAUSDT"] = {"symbol": "ADAUSDT", "poll_success": "YES", "poll_status": "READY"}

    traces = (
        _swing_trace("swing_active_0", stage="SWING_16M_CONFIRMED", progress_percent=20.0),
        _swing_trace("swing_invalidated_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True),
        _swing_trace("swing_completed_2", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True),
    )
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    tracked = [*state.setups.values(), *state.invalidated_setups.values(), *state.completed_setups.values()]
    assert tracked, "expected attempt rows to exist"
    assert not any(setup.current_state is SetupState.ENTRY_READY for setup in tracked), (
        "none of these synthetic traces is a real trade-detection ENTRY_READY setup"
    )

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "WAITING"
    assert result["reason"] == "No ENTRY_READY setup found."
    assert state.bitget_environment.orders == []


def _minute_candles(start: datetime, count: int) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            symbol="ADAUSDT",
            timeframe=Timeframe(1),
            timestamp=start + timedelta(minutes=index),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("10"),
        )
        for index in range(count)
    )


def test_stale_trade_candidate_reports_how_stale_in_candles_and_seconds() -> None:
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 10)  # latest candle timestamp = start + 9 minutes
    trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=5)).isoformat(),  # 4 candles before latest
        "source_16m_swing_id": "swing_stale_1",
    }

    stale = _stale_trade_candidates((trade,), candles, {"processed_trade_keys": []})

    assert len(stale) == 1
    # 4 candles closed after entry (minutes 6,7,8,9); window allows 1 of those
    # (the second-latest candle) to still count as fresh, so 3 candles past it.
    assert stale[0]["candles_past_window"] == 3
    assert stale[0]["seconds_past_window"] == 180


def test_fresh_trade_candidate_is_never_reported_as_stale() -> None:
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 10)
    fresh_latest = {"symbol": "ADAUSDT", "direction": "BEARISH", "entry_timestamp": (start + timedelta(minutes=9)).isoformat(), "source_16m_swing_id": "a"}
    fresh_second_latest = {"symbol": "ADAUSDT", "direction": "BEARISH", "entry_timestamp": (start + timedelta(minutes=8)).isoformat(), "source_16m_swing_id": "b"}

    stale = _stale_trade_candidates((fresh_latest, fresh_second_latest), candles, {"processed_trade_keys": []})

    assert stale == ()


def test_stale_skip_is_surfaced_on_the_matching_completed_setup_in_setup_radar() -> None:
    """The exact gap this closes: Setup Radar showed a COMPLETED/100% row with
    no indication that the matching real trade candidate was ever found and
    then silently skipped for being stale - this proves the two get joined
    by swing_16m_id and the skip detail reaches the API response."""
    api = client()
    state = get_state()
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 10)
    trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=5)).isoformat(),
        "source_16m_swing_id": "swing_completed_1",
    }
    stale = _stale_trade_candidates((trade,), candles, {"processed_trade_keys": []})
    _record_stale_skips_for_radar(state, stale)

    completed = _setup_from_trade(
        {
            "trade_id": "trade_completed_1",
            "symbol": "ADAUSDT",
            "direction": "BEARISH",
            "entry_timestamp": "2026-06-16T01:30:00+00:00",
            "entry_price": "100",
            "stop_loss": "120",
            "take_profit": "80",
            "source_12m_fvg_id": "fvg12_completed",
            "source_16m_swing_id": "swing_completed_1",
            "source_16m_fvg_id": "fvg16_completed",
        },
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    state.setups[completed.setup_id] = completed

    rows = {row["setup_id"]: row for row in api.get("/api/radar").json()["data"]}
    row = rows[completed.setup_id]

    assert row["stale_skip"] is not None
    assert row["stale_skip"]["candles_past_window"] == 3
    assert row["stale_skip"]["seconds_past_window"] == 180
    assert row["stale_skip"]["swing_16m_id"] == "swing_completed_1"
    assert row["stale_skip"]["skipped_at"]
    # No monitoring session was started in this test, so there is nothing to
    # classify as "near a restart" - must not be misreported as one.
    assert row["stale_skip"]["likely_restart_related"] is False
    assert row["stale_skip"]["seconds_since_monitoring_started"] is None

    # A setup with no matching stale skip must not show one at all.
    unrelated = _setup_from_trade(
        {
            "trade_id": "trade_completed_2",
            "symbol": "ETHUSDT",
            "direction": "BEARISH",
            "entry_timestamp": "2026-06-16T01:30:00+00:00",
            "entry_price": "100",
            "stop_loss": "120",
            "take_profit": "80",
            "source_12m_fvg_id": "fvg12_unrelated",
            "source_16m_swing_id": "swing_unrelated",
            "source_16m_fvg_id": "fvg16_unrelated",
        },
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    state.setups[unrelated.setup_id] = unrelated
    rows = {row["setup_id"]: row for row in api.get("/api/radar").json()["data"]}
    assert rows[unrelated.setup_id]["stale_skip"] is None


def test_stale_skip_soon_after_monitoring_started_is_classified_as_restart_catchup() -> None:
    """Distinguishes "still catching up on a backlog right after a restart"
    from "this happened well into an otherwise-continuous session" - the
    real evidence needed to confirm (or rule out) monitoring gaps as the
    actual cause of staleness, instead of guessing from polling-interval math
    alone."""
    state = get_state()
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 10)
    trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=5)).isoformat(),
        "source_16m_swing_id": "swing_restart_test",
    }
    stale = _stale_trade_candidates((trade,), candles, {"processed_trade_keys": []})

    state.monitoring["started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    _record_stale_skips_for_radar(state, stale)
    recorded = state.stale_trade_skips["swing_restart_test"]
    assert recorded["likely_restart_related"] is True
    assert recorded["seconds_since_monitoring_started"] is not None
    assert recorded["seconds_since_monitoring_started"] < RESTART_CATCHUP_WINDOW_SECONDS

    state.monitoring["started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=RESTART_CATCHUP_WINDOW_SECONDS + 60)).isoformat()
    _record_stale_skips_for_radar(state, stale)
    recorded = state.stale_trade_skips["swing_restart_test"]
    assert recorded["likely_restart_related"] is False
    assert recorded["seconds_since_monitoring_started"] > RESTART_CATCHUP_WINDOW_SECONDS


def test_fresh_trade_candidate_is_picked_up_even_when_its_entry_candle_is_long_past() -> None:
    """The actual fix for "100% of completed setups show Skipped (stale)":
    the shared strategy funnel only confirms ENTRY_READY once its full
    retrace window has elapsed, then searches that window front-to-back, so
    the tap satisfying entry is very often already many candles old the
    first time it is ever discovered - even with zero monitoring gap. A
    never-before-seen candidate must be treated as fresh regardless of how
    chronologically old its own entry candle is."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 30)  # latest candle timestamp = start + 29 minutes
    long_past_trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=2)).isoformat(),  # 26 candles before latest
        "source_16m_swing_id": "swing_long_past",
    }

    fresh = _fresh_trade_candidate((long_past_trade,), candles, {"processed_trade_keys": []})

    assert fresh is not None
    assert fresh["source_16m_swing_id"] == "swing_long_past"


def test_fresh_trade_candidate_never_returns_an_already_processed_trade() -> None:
    """processed_trade_keys, not chronological age, is what must gate
    re-execution - a trade already turned into a tracked setup on an earlier
    poll must never be returned again, no matter how the funnel re-discovers it."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 10)
    trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=5)).isoformat(),
        "source_16m_swing_id": "swing_already_done",
    }
    detector_state = {"processed_trade_keys": []}

    first = _fresh_trade_candidate((trade,), candles, detector_state)
    assert first is not None
    detector_state["processed_trade_keys"].append(_trade_key(trade))

    second = _fresh_trade_candidate((trade,), candles, detector_state)
    assert second is None


def test_fresh_trade_candidate_picks_the_most_recently_confirmed_never_seen_trade() -> None:
    """When more than one never-seen candidate exists in the same poll (a
    genuine backlog), the most recently-confirmed one is picked for
    execution this poll - the rest are left for _stale_trade_candidates to
    report as queued, picked up automatically on a later poll."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 30)
    older = {"symbol": "ADAUSDT", "direction": "BEARISH", "entry_timestamp": (start + timedelta(minutes=2)).isoformat(), "source_16m_swing_id": "swing_older"}
    newer = {"symbol": "ADAUSDT", "direction": "BEARISH", "entry_timestamp": (start + timedelta(minutes=10)).isoformat(), "source_16m_swing_id": "swing_newer"}

    fresh = _fresh_trade_candidate((older, newer), candles, {"processed_trade_keys": []})
    assert fresh["source_16m_swing_id"] == "swing_newer"

    queued = _stale_trade_candidates((older, newer), candles, {"processed_trade_keys": []}, exclude=fresh)
    assert len(queued) == 1
    assert queued[0]["source_16m_swing_id"] == "swing_older"


def test_suppress_redundant_attempt_trace_removes_only_the_attempt_tracer_row_for_that_swing() -> None:
    """Once a real ENTRY_READY trade is tracked for a swing, the
    attempt-tracer's own COMPLETED row for that same swing_16m_id must be
    dropped from completed_setups - otherwise one real-world completion
    shows as two rows (the exact "duplicate ETHUSDT" symptom reported)."""
    state = _fake_state("ADAUSDT", ())
    traces = (_swing_trace("swing_shared_0", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True),)
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    assert any(setup.swing_16m_id == "swing_shared_0" for setup in state.completed_setups.values())

    _suppress_redundant_attempt_trace(state, "swing_shared_0")

    assert not any(setup.swing_16m_id == "swing_shared_0" for setup in state.completed_setups.values())


def test_suppress_redundant_attempt_trace_never_removes_the_real_trade_row_itself() -> None:
    """The real ENTRY_READY trade's own completed_setups row carries
    metadata source LIVE_PROFILE_EVALUATOR - the suppression helper must
    never delete that one, only an attempt-tracer row sharing its swing_16m_id."""
    state = _fake_state("ADAUSDT", ())
    trade = {
        "trade_id": "trade_real_1",
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": "2026-06-16T01:30:00+00:00",
        "entry_price": "100",
        "stop_loss": "120",
        "take_profit": "80",
        "source_12m_fvg_id": "fvg12_real",
        "source_16m_swing_id": "swing_shared_real",
        "source_16m_fvg_id": "fvg16_real",
    }
    real_setup = _setup_from_trade(trade, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state.completed_setups[real_setup.setup_id] = real_setup

    _suppress_redundant_attempt_trace(state, "swing_shared_real")

    assert real_setup.setup_id in state.completed_setups


def test_real_csv_window_produces_no_duplicate_completed_row_for_the_same_swing() -> None:
    """End-to-end proof against real strategy data: the swing behind the real
    ENTRY_READY trade this window produces must not also still have its own
    separate attempt-tracer COMPLETED row sitting in completed_setups."""
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:150])

    detect_live_setups_for_symbol(state, "ADAUSDT")

    real_trades = [setup for setup in state.setups.values() if setup.current_state is SetupState.ENTRY_READY]
    assert real_trades, "fixture assumption: this window produces a real entry-ready trade"
    for real in real_trades:
        matching_completed = [
            setup
            for setup in state.completed_setups.values()
            if setup.swing_16m_id == real.swing_16m_id and setup.setup_id != real.setup_id
        ]
        assert matching_completed == [], (
            f"swing {real.swing_16m_id} has both a real trade and a redundant attempt-tracer completed row"
        )


def test_locked_tp_model_metadata_matches_what_was_actually_traded_not_a_stale_saved_setting() -> None:
    """PROFILE_2's tp_model (LEG_TARGET_RESEARCH) always wins over the
    operator's saved selected_rr_profile setting when actually computing
    stop/target (scripts/backtest_csv.py hardwires tp_model=profile.tp_model
    at the real trade-construction call site) - Setup.metadata's
    selected_tp_model/applied_tp_model must reflect that same reality,
    not echo back a stale/unrelated saved setting like RR_1_5."""
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:150])
    state.settings["selected_rr_profile"] = "RR_1_5"

    detect_live_setups_for_symbol(state, "ADAUSDT")

    real_trades = [setup for setup in state.setups.values() if setup.current_state is SetupState.ENTRY_READY]
    assert real_trades, "fixture assumption: this window produces a real entry-ready trade"
    for real in real_trades:
        assert real.metadata["selected_tp_model"] == "LEG_TARGET_RESEARCH"
        assert real.metadata["applied_tp_model"] == "LEG_TARGET_RESEARCH"
