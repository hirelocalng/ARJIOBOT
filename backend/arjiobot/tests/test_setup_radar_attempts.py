"""Tests for the Setup Radar live attempt tracker.

These prove the radar is a real setup-attempt tracker, not just an ENTRY_READY
trade log: every swing candidate becomes a visible, symbol-tagged attempt that
progresses or is invalidated through the chain, capped at the latest 100.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arjiobot.api.dependencies import get_state
from arjiobot.api.routes.radar import radar_record
from arjiobot.api.tests.helpers import client
from arjiobot.backtesting.historical_replay import load_ohlcv_csv
from arjiobot.exchange.bitget_environment import BitgetCredentialConfig, TradeMode
from arjiobot.live_automation import run_live_automation_once
import arjiobot.live_setup_detection as live_setup_detection
from arjiobot.live_setup_detection import (
    MAX_IN_PROGRESS_SETUPS,
    RESTART_CATCHUP_WINDOW_SECONDS,
    _apply_attempt_traces,
    _candidate_swing_filter_diagnostics,
    _fresh_trade_candidate,
    _record_stale_skips_for_radar,
    _setup_from_trade,
    _stale_trade_candidates,
    _suppress_redundant_attempt_trace,
    _trade_key,
    detect_live_setups_for_symbol,
    move_setup_to_completed,
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
        invalidated_setups=[],
        completed_setups=[],
        resolved_setup_ids=set(),
        resolved_swing_keys=set(),
        setup_history={},
        stale_trade_skips={},
        live_setup_detection={"processed_trade_keys": []},
        live_fvg_engines={},
    )


def _all_tracked(state) -> list:
    """Every setup across all three stores - mirrors radar.py's _all_setups."""
    return [*state.setups.values(), *state.invalidated_setups, *state.completed_setups]


def test_swing_only_attempt_is_logged_and_visible_with_its_symbol(monkeypatch) -> None:
    monkeypatch.setattr(live_setup_detection, "STALENESS_WINDOW_MINUTES", 999999)
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


def test_failed_expansion_attempt_is_retained_with_invalidation_reason(monkeypatch) -> None:
    monkeypatch.setattr(live_setup_detection, "STALENESS_WINDOW_MINUTES", 999999)
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])

    detect_live_setups_for_symbol(state, "ADAUSDT")

    # A failed/invalidated attempt now lives in invalidated_setups, not setups.
    expansion_failures = [
        setup
        for setup in state.invalidated_setups
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

    setup = _setup_from_trade(trade, state=_fake_state("ADAUSDT", ()), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")

    assert setup.symbol == "ADAUSDT"
    assert setup.progress_percent == 100.0
    assert setup.current_state is SetupState.ENTRY_READY
    assert setup.status is SetupStatus.ENTRY_READY


def _swing_trace(swing_id: str, *, stage: str, progress_percent: float, invalidation_reason: str | None = None, is_terminal: bool = False) -> dict[str, object]:
    offset_seconds = int(swing_id.split("_")[-1]) if swing_id.split("_")[-1].isdigit() else 0
    return {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "swing_16m_id": swing_id,
        "swing_timestamp": (datetime.now(timezone.utc) - timedelta(minutes=2) + timedelta(milliseconds=offset_seconds)).isoformat(),
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
    remaining_ids = {setup.swing_16m_id for setup in state.invalidated_setups}
    assert "swing_inv_104" in remaining_ids
    assert "swing_inv_0" not in remaining_ids


def test_structural_match_only_attempt_traces_land_in_invalidated_capped_at_100() -> None:
    """Fix 2 (Setup Radar journey): the attempt-tracer reaching ENTRY_READY
    structurally (every condition matched, but no real trade/execution ever
    happened for it) is NOT an execution outcome, so it must never land in
    COMPLETED - it lands in invalidated_setups instead, tagged
    NO_EXECUTION_ATTEMPTED, capped at 100 exactly like any other
    invalidation."""
    state = _fake_state("ADAUSDT", ())
    traces = tuple(_swing_trace(f"swing_done_{i}", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True) for i in range(105))
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert state.completed_setups == [], "structural-match-only traces must never land in COMPLETED"
    assert len(state.invalidated_setups) == 100
    assert state.setups == {}, "resolved setups must never land in the in-progress store"
    assert all(setup.invalidation_reason is InvalidationReason.NO_EXECUTION_ATTEMPTED for setup in state.invalidated_setups)
    remaining_ids = {setup.swing_16m_id for setup in state.invalidated_setups}
    assert "swing_done_104" in remaining_ids
    assert "swing_done_0" not in remaining_ids


def test_completed_history_via_real_trades_is_capped_at_100() -> None:
    """Now that COMPLETED is execution-only, the only way to fill it is the
    real trade path (_setup_from_trade -> move_setup_to_completed) - same
    append-only, capped-at-100 behavior as invalidated_setups."""
    state = _fake_state("ADAUSDT", ())
    trades = [
        _setup_from_trade(
            {
                "trade_id": f"trade_cap_{i}",
                "symbol": "ADAUSDT",
                "direction": "BEARISH",
                "entry_timestamp": (datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat(),
                "entry_price": "100",
                "stop_loss": "120",
                "take_profit": "80",
                "source_12m_fvg_id": f"fvg12_cap_{i}",
                "source_16m_swing_id": f"swing_cap_{i}",
                "source_16m_fvg_id": f"fvg16_cap_{i}",
            },
            state=state,
            profile_id="PROFILE_2",
            timeframe_profile_id="DEFAULT_16_12_8",
        )
        for i in range(105)
    ]
    for trade in trades:
        move_setup_to_completed(state, replace(trade, execution_status="trade_opened"))

    assert len(state.completed_setups) == 100
    remaining_ids = {setup.setup_id for setup in state.completed_setups}
    assert trades[104].setup_id in remaining_ids
    assert trades[0].setup_id not in remaining_ids


def test_completed_and_invalidated_mutations_persist_to_disk_in_progress_does_not(monkeypatch, tmp_path) -> None:
    """A setup landing in completed_setups or invalidated_setups must be
    written to setup_history_store.json (so an operator/log can see it
    without reading process memory); IN PROGRESS must never be written there
    at all - see setup_history_store.save_setup_history_store. Redirects the
    persisted file to a tmp_path so this never touches the real
    backend/data/ files."""
    import json

    from arjiobot.setup_tracker import setup_history_store

    monkeypatch.setattr(setup_history_store, "STORE_PATH", tmp_path / "setup_history_store.json")
    state = _fake_state("ADAUSDT", ())

    invalidated_trace = _swing_trace("swing_inv_persist_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
    _apply_attempt_traces(state, "ADAUSDT", (invalidated_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    # COMPLETED is execution-only now (Fix 2) - the only way to populate it is
    # the real trade path (_setup_from_trade -> move_setup_to_completed).
    real_trade = _setup_from_trade(
        {
            "trade_id": "trade_done_persist_1",
            "symbol": "ADAUSDT",
            "direction": "BEARISH",
            "entry_timestamp": "2026-06-24T01:30:00+00:00",
            "entry_price": "100",
            "stop_loss": "120",
            "take_profit": "80",
            "source_12m_fvg_id": "fvg12_done_persist",
            "source_16m_swing_id": "swing_done_persist_1",
            "source_16m_fvg_id": "fvg16_done_persist",
        },
        state=state,
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    move_setup_to_completed(state, replace(real_trade, execution_status="trade_opened"))
    in_progress_trace = _swing_trace("swing_active_persist_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0)
    _apply_attempt_traces(state, "ADAUSDT", (in_progress_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    payload = json.loads(setup_history_store.STORE_PATH.read_text(encoding="utf-8"))

    assert len(payload["completed"]) == 1
    assert len(payload["invalidated"]) == 1
    assert "swing_active_persist_1" not in json.dumps(payload), "IN PROGRESS must never be persisted"


def test_in_progress_pool_is_capped_at_max_in_progress_setups() -> None:
    """IN PROGRESS is capped at MAX_IN_PROGRESS_SETUPS (20) - the oldest
    entries are evicted when the cap is exceeded, keeping the pool bounded
    so the UI never floods with hundreds of backlog attempts."""
    state = _fake_state("ADAUSDT", ())
    traces = tuple(_swing_trace(f"swing_active_{i}", stage="SWING_16M_CONFIRMED", progress_percent=20.0) for i in range(150))
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert len(state.setups) == MAX_IN_PROGRESS_SETUPS
    assert state.invalidated_setups == []
    assert state.completed_setups == []


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
    pending = _setup_from_trade(pending_trade, state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state.setups[pending.setup_id] = pending

    traces = tuple(_swing_trace(f"swing_flood_{i}", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True) for i in range(105))
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert pending.setup_id in state.setups, "a pending ENTRY_READY setup must never be evicted"
    assert state.setups[pending.setup_id].status is SetupStatus.ENTRY_READY
    assert len(state.invalidated_setups) == 100, "the flood of unrelated structural-match-only rows must still respect its own cap"


def test_invalidated_setup_is_permanently_done_and_never_resurrected_by_a_later_poll() -> None:
    """Setup Radar journey rule (Fix 4): once a setup_id is invalidated, it is
    permanently done - the funnel re-deriving the exact same swing as
    ENTRY_READY on a later poll (the underlying check genuinely turning
    favorable, e.g. an expansion that takes more bars to confirm) must NOT
    un-invalidate or move it anywhere. This is also what keeps the
    append-only invalidated/completed lists stable between polls (Fix 2/3) -
    allowing a resurrection would mean removing and re-adding list entries
    instead of writing each one exactly once, ever."""
    state = _fake_state("ADAUSDT", ())
    base_trace = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "swing_16m_id": "swing_1",
        "swing_timestamp": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
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
    [setup] = state.invalidated_setups
    assert setup.status is SetupStatus.INVALIDATED
    assert setup.invalidation_reason is InvalidationReason.EXPANSION_NOT_CONFIRMED
    assert setup.invalidated_at is not None
    assert state.setups == {}
    assert setup.setup_id in state.resolved_setup_ids

    resolved_trace = {**base_trace, "stage": "ENTRY_READY", "progress_percent": 100.0, "invalidation_reason": None, "is_terminal": True}
    _apply_attempt_traces(state, "ADAUSDT", (resolved_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="LIVE_MARKET_DATA")
    # Byte-for-byte unchanged: still exactly the one invalidated entry, never
    # touched, and nothing was created in completed_setups or state.setups.
    assert state.invalidated_setups == [setup]
    assert state.completed_setups == []
    assert state.setups == {}


def test_live_automation_only_acts_on_entry_ready_setups() -> None:
    """Attempt-trace-derived rows (ACTIVE/INVALIDATED/COMPLETED) must never be
    picked up by run_live_automation_once - only a real ENTRY_READY setup from
    the existing, untouched trade-detection flow can trigger dry-run/submission.

    Uses the same fully-armed live state as test_live_automation_routes.py so
    preflight passes and the ENTRY_READY filter itself is what's exercised.
    Uses synthetic attempt traces (_apply_attempt_traces), not a real CSV
    detection window, to guarantee no real ENTRY_READY trade exists alongside
    them. This filter test should not depend on whether a given historical
    fixture happens to end on a latest-candle signal.
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
    tracked = [*state.setups.values(), *state.invalidated_setups, *state.completed_setups]
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


def test_stale_trade_candidate_reports_swing_age_beyond_staleness_window() -> None:
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 60)
    trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=58)).isoformat(),
        "source_16m_swing_id": "swing_stale_1",
        "source_16m_swing_timestamp": (start + timedelta(minutes=30)).isoformat(),
    }

    stale = _stale_trade_candidates((trade,), candles, {"processed_trade_keys": []})

    assert len(stale) == 1
    assert stale[0]["age_minutes"] == 29
    assert stale[0]["seconds_past_window"] == 300


def test_trade_candidate_with_fresh_swing_is_never_reported_as_stale() -> None:
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 60)
    fresh_old_entry = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=40)).isoformat(),
        "source_16m_swing_id": "a",
        "source_16m_swing_timestamp": (start + timedelta(minutes=50)).isoformat(),
    }
    stale_swing = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=58)).isoformat(),
        "source_16m_swing_id": "b",
        "source_16m_swing_timestamp": (start + timedelta(minutes=30)).isoformat(),
    }

    stale = _stale_trade_candidates((fresh_old_entry, stale_swing), candles, {"processed_trade_keys": []})

    assert len(stale) == 1
    assert stale[0]["source_16m_swing_id"] == "b"
    assert stale[0]["age_minutes"] == 29


def test_stale_attempt_trace_is_cached_and_never_enters_setup_radar() -> None:
    state = _fake_state("ADAUSDT", ())
    stale_timestamp = datetime.now(timezone.utc) - timedelta(minutes=25)
    trace = {
        **_swing_trace("swing_stale_trace_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0),
        "swing_timestamp": stale_timestamp.isoformat(),
    }

    _apply_attempt_traces(state, "ADAUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert state.setups == {}
    assert state.completed_setups == []
    assert state.invalidated_setups == []
    assert len(state.resolved_swing_keys) == 1


def test_candidate_swing_filter_diagnostics_explain_zero_funnel_candidates() -> None:
    state = _fake_state("ADAUSDT", ())
    now = datetime.now(timezone.utc)
    stale_swing = SimpleNamespace(
        symbol="ADAUSDT",
        swing_id="swg_stale_diag",
        right_candle=SimpleNamespace(timestamp=now - timedelta(minutes=25)),
    )

    fresh, diagnostics = _candidate_swing_filter_diagnostics(state, [stale_swing], direction="BEARISH", now=now)

    assert fresh == []
    assert diagnostics["raw_candidate_swings"] == 1
    assert diagnostics["fresh_candidate_swings"] == 0
    assert diagnostics["stale_filtered_swings"] == 1
    assert diagnostics["resolved_filtered_swings"] == 0
    assert diagnostics["newest_raw_swing_age_minutes"] == 25.0


def test_stale_filter_keeps_already_active_setup_evaluating(monkeypatch) -> None:
    state = _fake_state("ADAUSDT", ())
    swing_timestamp = datetime.now(timezone.utc) - timedelta(minutes=40)
    trace = {
        **_swing_trace("swing_active_1", stage="EXPANSION_16M_CONFIRMED", progress_percent=35.0),
        "swing_timestamp": swing_timestamp.isoformat(),
    }

    monkeypatch.setattr(live_setup_detection, "STALENESS_WINDOW_MINUTES", 999999)
    _apply_attempt_traces(state, "ADAUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    assert state.setups, "expected the old trace to be seeded as an active in-progress setup"

    monkeypatch.setattr(live_setup_detection, "STALENESS_WINDOW_MINUTES", 24)
    swing = SimpleNamespace(
        symbol="ADAUSDT",
        swing_id="swing_active_1",
        right_candle=SimpleNamespace(timestamp=swing_timestamp),
    )
    fresh, diagnostics = _candidate_swing_filter_diagnostics(state, [swing], direction="BEARISH", now=datetime.now(timezone.utc))

    assert fresh == [swing]
    assert diagnostics["fresh_candidate_swings"] == 1
    assert diagnostics["stale_filtered_swings"] == 0
    assert state.resolved_swing_keys == set()


def test_stale_skip_is_surfaced_on_the_matching_completed_setup_in_setup_radar() -> None:
    """The exact gap this closes: Setup Radar showed a COMPLETED/100% row with
    no indication that the matching real trade candidate was ever found and
    then silently skipped for being stale - this proves the two get joined
    by swing_16m_id and the skip detail reaches the API response."""
    api = client()
    state = get_state()
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 60)
    trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=58)).isoformat(),
        "source_16m_swing_id": "swing_completed_1",
        "source_16m_swing_timestamp": (start + timedelta(minutes=30)).isoformat(),
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
        state=state,
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    state.setups[completed.setup_id] = completed

    rows = {row["setup_id"]: row for row in api.get("/api/radar").json()["data"]}
    row = rows[completed.setup_id]

    assert row["stale_skip"] is not None
    assert row["stale_skip"]["age_minutes"] == 29
    assert row["stale_skip"]["seconds_past_window"] == 300
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
        state=state,
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
    candles = _minute_candles(start, 60)
    trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=58)).isoformat(),
        "source_16m_swing_id": "swing_restart_test",
        "source_16m_swing_timestamp": (start + timedelta(minutes=30)).isoformat(),
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


def test_fresh_trade_candidate_allows_old_entry_candle_when_swing_is_fresh() -> None:
    """The real-time gate is the swing timestamp, not the entry candle."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 30)  # latest candle timestamp = start + 29 minutes
    fresh_swing_trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=2)).isoformat(),  # 26 candles before latest
        "source_16m_swing_id": "swing_long_past",
        "source_16m_swing_timestamp": (start + timedelta(minutes=20)).isoformat(),
    }

    fresh = _fresh_trade_candidate((fresh_swing_trade,), candles, {"processed_trade_keys": []})

    assert fresh is not None
    assert fresh["source_16m_swing_id"] == "swing_long_past"
    assert _stale_trade_candidates((fresh_swing_trade,), candles, {"processed_trade_keys": []}) == ()


def test_fresh_trade_candidate_never_returns_an_already_processed_trade() -> None:
    """processed_trade_keys, not chronological age, is what must gate
    re-execution - a trade already turned into a tracked setup on an earlier
    poll must never be returned again, no matter how the funnel re-discovers it."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 10)
    trade = {
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": (start + timedelta(minutes=9)).isoformat(),
        "source_16m_swing_id": "swing_already_done",
        "source_16m_swing_timestamp": (start + timedelta(minutes=9)).isoformat(),
    }
    detector_state = {"processed_trade_keys": []}

    first = _fresh_trade_candidate((trade,), candles, detector_state)
    assert first is not None
    detector_state["processed_trade_keys"].append(_trade_key(trade))

    second = _fresh_trade_candidate((trade,), candles, detector_state)
    assert second is None


def test_fresh_trade_candidate_picks_fresh_swing_and_reports_stale_swing_backlog() -> None:
    """Only candidates with fresh swings are executable; older never-seen
    backlog candidates are reported stale instead of queued for later."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    candles = _minute_candles(start, 30)
    older = {"symbol": "ADAUSDT", "direction": "BEARISH", "entry_timestamp": (start + timedelta(minutes=29)).isoformat(), "source_16m_swing_id": "swing_older", "source_16m_swing_timestamp": (start + timedelta(minutes=2)).isoformat()}
    newer = {"symbol": "ADAUSDT", "direction": "BEARISH", "entry_timestamp": (start + timedelta(minutes=10)).isoformat(), "source_16m_swing_id": "swing_newer", "source_16m_swing_timestamp": (start + timedelta(minutes=29)).isoformat()}

    fresh = _fresh_trade_candidate((older, newer), candles, {"processed_trade_keys": []})
    assert fresh["source_16m_swing_id"] == "swing_newer"

    queued = _stale_trade_candidates((older, newer), candles, {"processed_trade_keys": []}, exclude=fresh)
    assert len(queued) == 1
    assert queued[0]["source_16m_swing_id"] == "swing_older"


def test_suppress_redundant_attempt_trace_removes_only_the_attempt_tracer_row_for_that_swing() -> None:
    """Once a real ENTRY_READY trade is tracked for a swing, the
    attempt-tracer's own NO_EXECUTION_ATTEMPTED row for that same
    swing_16m_id must be dropped from invalidated_setups - otherwise one
    real-world completion shows as two rows (the exact "duplicate ETHUSDT"
    symptom reported)."""
    state = _fake_state("ADAUSDT", ())
    traces = (_swing_trace("swing_shared_0", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True),)
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    assert any(setup.swing_16m_id == "swing_shared_0" for setup in state.invalidated_setups)

    _suppress_redundant_attempt_trace(state, "swing_shared_0")

    assert not any(setup.swing_16m_id == "swing_shared_0" for setup in state.invalidated_setups)


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
    real_setup = _setup_from_trade(trade, state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state.completed_setups.insert(0, real_setup)

    _suppress_redundant_attempt_trace(state, "swing_shared_real")

    assert any(setup.setup_id == real_setup.setup_id for setup in state.completed_setups)


def test_real_entry_ready_setup_takes_over_the_attempt_tracers_setup_id() -> None:
    """The real setup must keep the exact setup_id (and created_at) it was
    already tracked under in IN_PROGRESS as an attempt-tracer row - a true
    identity hand-off, not a different id that requires the old row to be
    separately deleted (_suppress_redundant_attempt_trace is now only a
    defensive backstop, not how this is normally resolved)."""
    state = _fake_state("ADAUSDT", ())
    swing_id = "swing_handoff_1"
    in_progress_trace = _swing_trace(swing_id, stage="FVG_8M_CONFIRMED", progress_percent=80.0)
    _apply_attempt_traces(state, "ADAUSDT", (in_progress_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    [tracked] = state.setups.values()
    assert tracked.current_state is SetupState.FVG_8M_CONFIRMED

    trade = {
        "trade_id": "trade_handoff_1",
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": "2026-06-16T01:30:00+00:00",
        "entry_price": "100",
        "stop_loss": "120",
        "take_profit": "80",
        "source_12m_fvg_id": "fvg12_handoff",
        "source_16m_swing_id": swing_id,
        "source_16m_fvg_id": "fvg16_handoff",
    }
    real_setup = _setup_from_trade(trade, state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")

    assert real_setup.setup_id == tracked.setup_id, "the real setup must keep the same setup_id the swing was tracked under in IN_PROGRESS"
    assert real_setup.created_at == tracked.created_at, "created_at must still reflect when the setup was first detected, not the entry-tap time"
    assert real_setup.current_state is SetupState.ENTRY_READY
    assert real_setup.status is SetupStatus.ENTRY_READY


def test_attempt_tracer_structural_match_on_first_poll_is_recorded_in_in_progress_first() -> None:
    """The fix for setups skipping IN PROGRESS entirely: a swing whose very
    first observed trace already reaches ENTRY_READY structurally (no real
    execution ever attempted for it) must still be recorded in IN PROGRESS
    (state.setup_history) before the terminal INVALIDATED/NO_EXECUTION_ATTEMPTED
    entry - never go straight from never-seen to INVALIDATED."""
    state = _fake_state("ADAUSDT", ())
    trace = {**_swing_trace("swing_instant_complete_1", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True), "entry_timestamp": "2026-06-16T01:30:00+00:00"}
    _apply_attempt_traces(state, "ADAUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    [setup] = state.invalidated_setups
    assert setup.status is SetupStatus.INVALIDATED
    assert setup.invalidation_reason is InvalidationReason.NO_EXECUTION_ATTEMPTED
    assert setup.setup_id not in state.setups, "it must have moved on to invalidated_setups, not stayed in IN PROGRESS"
    history = state.setup_history[setup.setup_id]
    assert len(history) == 2, f"expected an IN PROGRESS entry before the terminal INVALIDATED entry, got: {history}"
    assert history[0]["reason"] == "recorded in IN PROGRESS before resolving in the same poll"
    assert history[0]["to_state"] == SetupState.FVG_8M_CONFIRMED.value
    assert history[1]["to_state"] == SetupState.INVALIDATED.value


def test_attempt_tracer_setup_invalidating_on_first_poll_is_recorded_in_in_progress_first() -> None:
    """Mirror of the COMPLETED case: a swing that invalidates on the very
    first poll it is ever observed on must still be recorded in IN PROGRESS
    (at the last valid stage it actually reached) before the terminal
    INVALIDATED entry."""
    state = _fake_state("ADAUSDT", ())
    trace = _swing_trace("swing_instant_invalid_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
    _apply_attempt_traces(state, "ADAUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    [setup] = state.invalidated_setups
    assert setup.status is SetupStatus.INVALIDATED
    assert setup.setup_id not in state.setups, "it must have moved on to invalidated_setups, not stayed in IN PROGRESS"
    history = state.setup_history[setup.setup_id]
    assert len(history) == 2, f"expected an IN PROGRESS entry before the terminal INVALIDATED entry, got: {history}"
    assert history[0]["reason"] == "recorded in IN PROGRESS before resolving in the same poll"
    assert history[0]["to_state"] == SetupState.SWING_16M_CONFIRMED.value
    assert history[1]["to_state"] == SetupState.INVALIDATED.value


def test_real_trade_on_first_poll_is_recorded_in_in_progress_before_entry_ready(monkeypatch) -> None:
    """Mirror of the attempt-tracer fix for the _setup_from_trade path: a
    swing whose very first poll already produces a real, tradable
    ENTRY_READY trade must still be recorded in IN PROGRESS before
    ENTRY_READY - not go straight from never-seen to ENTRY_READY with no IN
    PROGRESS history at all. The attempt-tracer (which runs first each poll)
    and _setup_from_trade share this swing's setup_id (see
    _find_tracked_setup_by_swing), so the full real chain is IN PROGRESS ->
    COMPLETED (attempt-tracer's own terminal marker) -> ENTRY_READY (the
    real trade taking over that same id) - all under one setup_id, with the
    IN PROGRESS entry always first."""
    monkeypatch.setattr(live_setup_detection, "STALENESS_WINDOW_MINUTES", 999999)
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:150])

    detect_live_setups_for_symbol(state, "ADAUSDT")

    real_trades = [setup for setup in state.setups.values() if setup.current_state is SetupState.ENTRY_READY]
    assert real_trades, "fixture assumption: this window produces a real entry-ready trade"
    for real in real_trades:
        history = state.setup_history[real.setup_id]
        assert len(history) >= 2, f"setup {real.setup_id} must have an IN PROGRESS entry recorded before ENTRY_READY, got: {history}"
        assert history[0]["reason"] == "recorded in IN PROGRESS before resolving in the same poll"
        assert history[0]["to_state"] not in (SetupState.ENTRY_READY.value, SetupState.COMPLETED.value, SetupState.INVALIDATED.value)
        assert history[-1]["to_state"] == SetupState.ENTRY_READY.value


def test_real_csv_window_produces_no_duplicate_completed_row_for_the_same_swing(monkeypatch) -> None:
    """End-to-end proof against real strategy data: the swing behind the real
    ENTRY_READY trade this window produces must not also still have its own
    separate attempt-tracer COMPLETED row sitting in completed_setups."""
    monkeypatch.setattr(live_setup_detection, "STALENESS_WINDOW_MINUTES", 999999)
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:150])

    detect_live_setups_for_symbol(state, "ADAUSDT")

    real_trades = [setup for setup in state.setups.values() if setup.current_state is SetupState.ENTRY_READY]
    assert real_trades, "fixture assumption: this window produces a real entry-ready trade"
    for real in real_trades:
        matching_completed = [
            setup
            for setup in state.completed_setups
            if setup.swing_16m_id == real.swing_16m_id and setup.setup_id != real.setup_id
        ]
        assert matching_completed == [], (
            f"swing {real.swing_16m_id} has both a real trade and a redundant attempt-tracer completed row"
        )


def test_locked_tp_model_metadata_matches_what_was_actually_traded_not_a_stale_saved_setting(monkeypatch) -> None:
    """PROFILE_2's tp_model (LEG_TARGET_RESEARCH) always wins over the
    operator's saved selected_rr_profile setting when actually computing
    stop/target (scripts/backtest_csv.py hardwires tp_model=profile.tp_model
    at the real trade-construction call site) - Setup.metadata's
    selected_tp_model/applied_tp_model must reflect that same reality,
    not echo back a stale/unrelated saved setting like RR_1_5."""
    monkeypatch.setattr(live_setup_detection, "STALENESS_WINDOW_MINUTES", 999999)
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:150])
    state.settings["selected_rr_profile"] = "RR_1_5"

    detect_live_setups_for_symbol(state, "ADAUSDT")

    real_trades = [setup for setup in state.setups.values() if setup.current_state is SetupState.ENTRY_READY]
    assert real_trades, "fixture assumption: this window produces a real entry-ready trade"
    for real in real_trades:
        assert real.metadata["selected_tp_model"] == "LEG_TARGET_RESEARCH"
        assert real.metadata["applied_tp_model"] == "LEG_TARGET_RESEARCH"


# --- Setup Radar rebuild: stage/progress display, last_valid_stage, completed_at ---


def test_setup_created_in_progress_on_16m_swing_detection() -> None:
    """A setup attempt must be created with status IN_PROGRESS (ACTIVE) the
    moment a 16M swing is detected, visible via the radar_record() API shape
    at current_stage=16M_SWING_DETECTED / progress_pct=10."""
    state = _fake_state("ADAUSDT", ())
    trace = _swing_trace("swing_new_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0)
    _apply_attempt_traces(state, "ADAUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    [setup] = state.setups.values()
    assert setup.status is SetupStatus.ACTIVE
    record = radar_record(setup)
    assert record["status"] == "ACTIVE"
    assert record["current_stage"] == "16M_SWING_DETECTED"
    assert record["progress_pct"] == 10.0


def test_progress_pct_advances_through_every_stage_including_waiting_retrace() -> None:
    """progress_pct/current_stage must advance through the exact stage->percent
    mapping: 16M_SWING_DETECTED=10, 16M_EXPANSION_DETECTED=25, 16M_FVG_DETECTED=40,
    12M_FVG_DETECTED=55, 8M_FVG_DETECTED=70, WAITING_RETRACE=85, ENTRY_READY=100.
    WAITING_RETRACE has no equivalent internal SetupState - it is the same
    FVG_8M_CONFIRMED stage with retrace_candle_found=True (see radar.py)."""
    expectations = (
        ("SWING_16M_CONFIRMED", 20.0, False, "16M_SWING_DETECTED", 10.0),
        ("EXPANSION_16M_CONFIRMED", 35.0, False, "16M_EXPANSION_DETECTED", 25.0),
        ("FVG_16M_CONFIRMED", 50.0, False, "16M_FVG_DETECTED", 40.0),
        ("FVG_12M_CONFIRMED", 65.0, False, "12M_FVG_DETECTED", 55.0),
        ("FVG_8M_CONFIRMED", 80.0, False, "8M_FVG_DETECTED", 70.0),
        ("FVG_8M_CONFIRMED", 80.0, True, "WAITING_RETRACE", 85.0),
    )
    for index, (stage, internal_pct, retrace_found, expected_stage, expected_pct) in enumerate(expectations):
        state = _fake_state("ADAUSDT", ())
        trace = {**_swing_trace(f"swing_stage_{index}", stage=stage, progress_percent=internal_pct), "retrace_candle_found": retrace_found}
        _apply_attempt_traces(state, "ADAUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
        [setup] = _all_tracked(state)
        record = radar_record(setup)
        assert record["current_stage"] == expected_stage, f"stage {stage} (retrace_found={retrace_found})"
        assert record["progress_pct"] == expected_pct, f"stage {stage} (retrace_found={retrace_found})"

    # ENTRY_READY/100% display mapping is exercised through the real trade
    # path (_setup_from_trade), not an attempt trace - the attempt-tracer
    # reaching ENTRY_READY structurally is a different, INVALIDATED/
    # NO_EXECUTION_ATTEMPTED outcome now (Fix 2), not this stage's ENTRY_READY.
    entry_ready = _setup_from_trade(
        {
            "trade_id": "trade_stage_entry_ready",
            "symbol": "ADAUSDT",
            "direction": "BEARISH",
            "entry_timestamp": "2026-06-16T01:30:00+00:00",
            "entry_price": "100",
            "stop_loss": "120",
            "take_profit": "80",
            "source_12m_fvg_id": "fvg12_stage_entry_ready",
            "source_16m_swing_id": "swing_stage_entry_ready",
            "source_16m_fvg_id": "fvg16_stage_entry_ready",
        },
        state=_fake_state("ADAUSDT", ()),
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    record = radar_record(entry_ready)
    assert record["current_stage"] == "ENTRY_READY"
    assert record["progress_pct"] == 100.0


def test_invalidated_setup_carries_reason_and_last_valid_stage() -> None:
    """An invalidated setup must record InvalidationReason and the last stage
    that was actually reached before the failing check - exposed via
    radar_record() as invalidation_reason/last_valid_stage."""
    state = _fake_state("ADAUSDT", ())
    # Reaches FVG_16M_CONFIRMED (40% on the display scale) then fails to find a 12M FVG.
    trace = {
        **_swing_trace("swing_lvs_1", stage="FVG_16M_CONFIRMED", progress_percent=50.0, invalidation_reason="FVG_12M_NOT_FOUND", is_terminal=True),
        "failure_detail": "NO_12M_FVG_INSIDE_16M_LEG candidates_after_16m=2 direction=BEARISH",
        "fvg_12m_candidates_after_16m": 2,
        "fvg_12m_candidates_inside_leg": 0,
        "fvg_leg_high": "120",
        "fvg_leg_low": "80",
    }
    _apply_attempt_traces(state, "ADAUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    [setup] = state.invalidated_setups
    assert setup.status is SetupStatus.INVALIDATED
    assert setup.invalidation_reason is InvalidationReason.FVG_12M_NOT_FOUND
    assert setup.last_valid_stage == "FVG_16M_CONFIRMED"
    record = radar_record(setup)
    assert record["status"] == "INVALIDATED"
    assert record["invalidation_reason"] == "FVG_12M_NOT_FOUND"
    assert record["last_valid_stage"] == "16M_FVG_DETECTED"
    assert record["progress_pct"] == 40.0, "% reached before invalidation must use the last valid stage, not the terminal state"
    assert record["diagnostics"]["failure_detail"] == "NO_12M_FVG_INSIDE_16M_LEG candidates_after_16m=2 direction=BEARISH"
    assert record["diagnostics"]["fvg_12m_candidates_after_16m"] == "2"
    assert record["diagnostics"]["fvg_leg_high"] == "120"
    assert record["diagnostics"]["fvg_leg_low"] == "80"


def test_structural_match_only_setup_lands_in_invalidated_with_no_completed_at() -> None:
    """Once an attempt trace reaches ENTRY_READY/100% structurally with no
    real execution ever attempted for it (Fix 2), the resulting row must land
    in invalidated_setups (NO_EXECUTION_ATTEMPTED) - and, unlike a real trade,
    completed_at (the entry-tap timestamp) must stay unset, since this row's
    chain never actually went through execution."""
    state = _fake_state("ADAUSDT", ())
    trace = {
        **_swing_trace("swing_completedat_1", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True),
        "entry_timestamp": "2026-06-16T03:45:00+00:00",
    }
    _apply_attempt_traces(state, "ADAUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert state.setups == {}
    assert state.completed_setups == []
    [setup] = state.invalidated_setups
    assert setup.status is SetupStatus.INVALIDATED
    assert setup.invalidation_reason is InvalidationReason.NO_EXECUTION_ATTEMPTED
    assert setup.completed_at is None
    record = radar_record(setup)
    assert record["current_stage"] == "INVALIDATED"
    assert record["progress_pct"] == 100.0


def test_real_trade_moved_to_completed_has_completed_at_set() -> None:
    """A real trade (the only legitimate path into COMPLETED now - Fix 2)
    must land in completed_setups with completed_at set to the real
    entry-tap timestamp, not left as None."""
    state = _fake_state("ADAUSDT", ())
    trade = _setup_from_trade(
        {
            "trade_id": "trade_completedat_1",
            "symbol": "ADAUSDT",
            "direction": "BEARISH",
            "entry_timestamp": "2026-06-16T03:45:00+00:00",
            "entry_price": "100",
            "stop_loss": "120",
            "take_profit": "80",
            "source_12m_fvg_id": "fvg12_completedat",
            "source_16m_swing_id": "swing_completedat_real",
            "source_16m_fvg_id": "fvg16_completedat",
        },
        state=state,
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    move_setup_to_completed(state, replace(trade, execution_status="trade_opened"))

    [setup] = state.completed_setups
    assert setup.execution_status == "trade_opened"
    assert setup.completed_at is not None
    assert setup.completed_at.isoformat() == "2026-06-16T03:45:00+00:00"
    record = radar_record(setup)
    assert record["completed_at"] == "2026-06-16T03:45:00+00:00"
    assert record["current_stage"] == "ENTRY_READY"
    assert record["progress_pct"] == 100.0


def test_only_entry_ready_setup_allowed_into_execution_flow_not_in_progress_or_invalidated() -> None:
    """Re-confirms requirement #7/#8 directly against the three stores: an
    IN_PROGRESS (ACTIVE) setup and an INVALIDATED setup must never be eligible
    for execution - only a real ENTRY_READY setup (status ENTRY_READY, from
    the untouched _setup_from_trade trade-detection path) is. This mirrors
    what test_live_automation_only_acts_on_entry_ready_setups proves through
    the live HTTP route, asserted here directly against setup.status."""
    state = _fake_state("ADAUSDT", ())
    in_progress_trace = _swing_trace("swing_eligact_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0)
    invalidated_trace = _swing_trace("swing_eliginv_2", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
    _apply_attempt_traces(state, "ADAUSDT", (in_progress_trace, invalidated_trace), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    def executable(setup) -> bool:
        return setup.status in (SetupStatus.ENTRY_READY, SetupStatus.COMPLETED) and setup.current_state is SetupState.ENTRY_READY

    [active_setup] = state.setups.values()
    [invalidated_setup] = state.invalidated_setups
    assert not executable(active_setup), "IN_PROGRESS setups must never be eligible for execution"
    assert not executable(invalidated_setup), "INVALIDATED setups must never be eligible for execution"

    entry_ready = _setup_from_trade(
        {
            "trade_id": "trade_eligibility_1",
            "symbol": "ADAUSDT",
            "direction": "BEARISH",
            "entry_timestamp": "2026-06-16T01:30:00+00:00",
            "entry_price": "100",
            "stop_loss": "120",
            "take_profit": "80",
            "source_12m_fvg_id": "fvg12_eligibility",
            "source_16m_swing_id": "swing16_eligibility",
            "source_16m_fvg_id": "fvg16_eligibility",
        },
        state=state,
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    assert entry_ready.status is SetupStatus.ENTRY_READY
    assert executable(entry_ready), "a real ENTRY_READY setup must be eligible for execution"


# --- Setup Radar journey: append-only stability, seen-setups dedup --------


def test_invalidated_list_at_cap_drops_only_the_oldest_order_of_others_unchanged() -> None:
    """Explicit scenario: INVALIDATED list at exactly 100 -> one new entry
    added -> the oldest is dropped and every other entry's relative order is
    completely unchanged (no re-sort, no rebuild - see _append_resolved_setup)."""
    state = _fake_state("ADAUSDT", ())
    traces = tuple(
        _swing_trace(f"swing_cap_{i}", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
        for i in range(100)
    )
    _apply_attempt_traces(state, "ADAUSDT", traces, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    assert len(state.invalidated_setups) == 100
    before = list(state.invalidated_setups)  # newest-first: [swing_99, swing_98, ..., swing_0]

    one_more = _swing_trace("swing_cap_100", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
    _apply_attempt_traces(state, "ADAUSDT", (one_more,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert len(state.invalidated_setups) == 100
    assert state.invalidated_setups[0].swing_16m_id == "swing_cap_100", "the new entry is prepended to the front"
    assert state.invalidated_setups[1:] == before[:-1], "every other entry's relative order is byte-for-byte unchanged"
    assert before[-1] not in state.invalidated_setups, "only the oldest (now evicted) entry is gone"


def test_two_polls_with_no_new_events_leave_all_three_stores_byte_for_byte_identical() -> None:
    """Stability test: re-running the exact same poll (both swings already
    resolved into invalidated_setups on the first pass - one a genuine
    strategy failure, one a structural-match-only/NO_EXECUTION_ATTEMPTED row)
    must not change IN PROGRESS, COMPLETED, or INVALIDATED at all on the
    second pass - not even re-create the same object - because the
    swing-level dedup cache (resolved_swing_keys) stops the funnel from
    re-deriving either swing at all, and resolved_setup_ids additionally
    short-circuits _apply_one_attempt_trace for an already-resolved
    setup_id."""
    state = _fake_state("ADAUSDT", ())
    strategy_failed_trace = _swing_trace("swing_stable_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
    structural_match_trace = {**_swing_trace("swing_stable_2", stage="ENTRY_READY", progress_percent=100.0, is_terminal=True), "entry_timestamp": "2026-06-16T01:30:00+00:00"}
    _apply_attempt_traces(state, "ADAUSDT", (strategy_failed_trace, structural_match_trace), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    in_progress_after_poll_1 = dict(state.setups)
    invalidated_after_poll_1 = list(state.invalidated_setups)
    assert in_progress_after_poll_1 == {}
    assert len(invalidated_after_poll_1) == 2
    assert state.completed_setups == []

    # Second poll: the exact same traces again - nothing new happened.
    _apply_attempt_traces(state, "ADAUSDT", (strategy_failed_trace, structural_match_trace), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert state.setups == in_progress_after_poll_1
    assert state.invalidated_setups == invalidated_after_poll_1
    assert state.completed_setups == []
    # Not just equal - the identical objects, never replaced or re-appended.
    assert state.invalidated_setups[0] is invalidated_after_poll_1[0]
    assert state.invalidated_setups[1] is invalidated_after_poll_1[1]
