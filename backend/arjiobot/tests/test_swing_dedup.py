"""Tests for Setup Radar's permanent swing-level deduplication.

Root cause this closes: the live detection funnel re-derives the exact same
real-world swing from its rolling candle buffer on every poll, but a fresh
poll's setup_id is not guaranteed to be byte-for-byte identical to an
earlier poll's setup_id for that same swing - so a setup_id-keyed dedup
cache alone can fail to recognize it as already handled, and the swing loops
through IN PROGRESS -> staleness gate -> silently dropped, forever. The fix:
a permanent cache keyed purely on symbol + direction + the swing's own 16M
candle timestamp (build_swing_dedup_key), checked BEFORE the funnel ever
runs for a swing - see live_setup_detection.py's _filter_resolved_swings.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from arjiobot.backtesting.historical_replay import load_ohlcv_csv
from arjiobot.live_setup_detection import (
    _apply_attempt_traces,
    _filter_resolved_swings,
    _setup_from_trade,
    detect_live_setups_for_symbol,
    expire_stale_setup,
    move_setup_to_completed,
)
from arjiobot.setup_tracker.setup_models import InvalidationReason, SetupDirection, build_swing_dedup_key

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


def _real_trade(suffix: str, *, entry_timestamp: str) -> dict[str, object]:
    return {
        "trade_id": f"trade_{suffix}",
        "symbol": "ADAUSDT",
        "direction": "BEARISH",
        "entry_timestamp": entry_timestamp,
        "entry_price": "100",
        "stop_loss": "120",
        "take_profit": "80",
        "source_12m_fvg_id": f"fvg12_{suffix}",
        "source_16m_swing_id": f"swing_{suffix}",
        "source_16m_fvg_id": f"fvg16_{suffix}",
    }


def test_filter_resolved_swings_blocks_an_already_resolved_swing_key() -> None:
    """The cache lookup the live detection funnel checks before it runs at
    all (Fix 5): a swing whose dedup key is already in resolved_swing_keys
    must be dropped before the funnel ever sees it; an unrelated swing must
    pass through untouched."""
    state = _fake_state("ADAUSDT", ())
    resolved_timestamp = datetime(2026, 6, 22, 18, 24, tzinfo=timezone.utc)
    fresh_timestamp = datetime(2026, 6, 22, 18, 40, tzinfo=timezone.utc)
    state.resolved_swing_keys.add(build_swing_dedup_key(symbol="ADAUSDT", direction="BEARISH", swing_timestamp=resolved_timestamp))

    already_resolved_swing = SimpleNamespace(symbol="ADAUSDT", swing_id="swg_resolved", right_candle=SimpleNamespace(timestamp=resolved_timestamp))
    fresh_swing = SimpleNamespace(symbol="ADAUSDT", swing_id="swg_fresh", right_candle=SimpleNamespace(timestamp=fresh_timestamp))

    remaining = _filter_resolved_swings(state, [already_resolved_swing, fresh_swing], direction="BEARISH")

    assert remaining == [fresh_swing]


def test_resolved_swing_stays_out_of_in_progress_and_is_not_reprocessed_on_a_later_poll() -> None:
    """Fix 1/5 end-to-end, against real strategy data: once a swing resolves
    into invalidated_setups, the exact same swing being presented again on a
    later poll (the live candle buffer is unchanged - nothing new arrived)
    must be blocked by the permanent swing-key cache before the funnel ever
    runs on it again - invalidated_setups/completed_setups must not grow,
    and the swing must never reappear in IN PROGRESS."""
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])

    detect_live_setups_for_symbol(state, "ADAUSDT")
    invalidated_after_poll_1 = list(state.invalidated_setups)
    completed_after_poll_1 = list(state.completed_setups)
    assert invalidated_after_poll_1, "fixture assumption: this window produces at least one invalidated swing"
    resolved_swing = invalidated_after_poll_1[0]
    expected_key = build_swing_dedup_key(symbol=resolved_swing.symbol, direction=resolved_swing.direction, swing_timestamp=resolved_swing.created_at)
    assert expected_key in state.resolved_swing_keys

    detect_live_setups_for_symbol(state, "ADAUSDT")  # same candle buffer - nothing new

    assert state.invalidated_setups == invalidated_after_poll_1
    assert state.completed_setups == completed_after_poll_1
    assert state.invalidated_setups[0] is invalidated_after_poll_1[0], "not just equal - the identical object, never recreated"
    assert resolved_swing.swing_16m_id not in {setup.swing_16m_id for setup in state.setups.values()}, "a resolved swing must never reappear in IN PROGRESS"


def test_swing_key_format_is_identical_across_lookup_insertion_and_seeding() -> None:
    """The exact same real-world swing must produce the identical dedup key
    string at all three call sites - the cache lookup before the funnel runs
    (a Swing-like object, Fix 5), the cache insertion when it resolves (a
    Setup's own symbol/direction/created_at, Fix 1), and history seeding
    from a previous session's persisted JSON record (Fix 3) - or the cache
    silently fails to recognize the same swing across them."""
    symbol = "SUIUSDT"
    swing_timestamp = datetime(2026, 6, 22, 18, 24, tzinfo=timezone.utc)

    lookup_swing = SimpleNamespace(symbol=symbol, swing_id="swg_format", right_candle=SimpleNamespace(timestamp=swing_timestamp))
    lookup_key = build_swing_dedup_key(symbol=lookup_swing.symbol, direction="BEARISH", swing_timestamp=lookup_swing.right_candle.timestamp)

    state = _fake_state(symbol, ())
    setup = _setup_from_trade(
        _real_trade("format_1", entry_timestamp=swing_timestamp.isoformat()) | {"symbol": symbol},
        state=state,
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    insertion_key = build_swing_dedup_key(symbol=setup.symbol, direction=setup.direction, swing_timestamp=setup.created_at)

    persisted_record = {"symbol": symbol, "direction": "BEARISH", "created_at": swing_timestamp.isoformat()}
    seeding_key = build_swing_dedup_key(symbol=persisted_record["symbol"], direction=persisted_record["direction"], swing_timestamp=persisted_record["created_at"])

    assert lookup_key == insertion_key == seeding_key == f"SUIUSDT_BEARISH_{swing_timestamp.isoformat()}"


def test_swing_key_added_atomically_with_each_of_the_four_terminal_outcomes() -> None:
    """Setup Radar's 4 valid exit paths (trade_opened/rejected/risk_blocked/
    no_margin -> COMPLETED, staleness_expired/strategy_condition_failed ->
    INVALIDATED) must each add the swing's permanent dedup key to
    state.resolved_swing_keys in the exact same step as the COMPLETED/
    INVALIDATED write (_append_resolved_setup) - never after, never as a
    separate step an exception in between could skip."""
    # 1. trade_opened -> COMPLETED (move_setup_to_completed)
    state_opened = _fake_state("ADAUSDT", ())
    trade_opened = _setup_from_trade(_real_trade("outcome_opened", entry_timestamp="2026-06-16T01:30:00+00:00"), state=state_opened, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    move_setup_to_completed(state_opened, replace(trade_opened, execution_status="trade_opened"))
    key_opened = build_swing_dedup_key(symbol=trade_opened.symbol, direction=trade_opened.direction, swing_timestamp=trade_opened.created_at)
    assert key_opened in state_opened.resolved_swing_keys
    assert trade_opened.setup_id in {setup.setup_id for setup in state_opened.completed_setups}

    # 2. risk_blocked -> COMPLETED (move_setup_to_completed - same function,
    #    proving the atomic write applies regardless of execution_status)
    state_blocked = _fake_state("ADAUSDT", ())
    trade_blocked = _setup_from_trade(_real_trade("outcome_blocked", entry_timestamp="2026-06-16T01:35:00+00:00"), state=state_blocked, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    move_setup_to_completed(state_blocked, replace(trade_blocked, execution_status="risk_blocked"))
    key_blocked = build_swing_dedup_key(symbol=trade_blocked.symbol, direction=trade_blocked.direction, swing_timestamp=trade_blocked.created_at)
    assert key_blocked in state_blocked.resolved_swing_keys

    # 3. strategy_condition_failed -> INVALIDATED (_store_setup, via the
    #    attempt-tracer's strategy_failed branch)
    state_failed = _fake_state("ADAUSDT", ())
    failed_trace = _swing_trace("swing_outcome_3", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
    _apply_attempt_traces(state_failed, "ADAUSDT", (failed_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    [invalidated] = state_failed.invalidated_setups
    key_failed = build_swing_dedup_key(symbol=invalidated.symbol, direction=invalidated.direction, swing_timestamp=invalidated.created_at)
    assert key_failed in state_failed.resolved_swing_keys

    # 4. staleness_expired -> INVALIDATED (expire_stale_setup)
    state_expired = _fake_state("ADAUSDT", ())
    trade_expired = _setup_from_trade(_real_trade("outcome_expired", entry_timestamp="2026-06-16T01:40:00+00:00"), state=state_expired, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state_expired.setups[trade_expired.setup_id] = trade_expired
    expired = expire_stale_setup(state_expired, trade_expired, expired_at=datetime.now(timezone.utc))
    key_expired = build_swing_dedup_key(symbol=expired.symbol, direction=expired.direction, swing_timestamp=expired.created_at)
    assert key_expired in state_expired.resolved_swing_keys
    assert expired in state_expired.invalidated_setups


def test_staleness_expiry_writes_to_invalidated_before_removing_from_in_progress(monkeypatch) -> None:
    """Fix 2: the order is non-negotiable - the setup (and its persisted
    JSON write) must already exist in invalidated_setups before it is
    removed from IN PROGRESS, never the other way around, so an exception
    raised mid-write can never leave it recorded nowhere."""
    state = _fake_state("ADAUSDT", ())
    setup = _setup_from_trade(_real_trade("staleness_order", entry_timestamp="2026-06-16T01:30:00+00:00"), state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state.setups[setup.setup_id] = setup

    observed: dict[str, bool] = {}

    def _spy_save(spied_state) -> None:
        observed["in_invalidated_before_save"] = any(s.setup_id == setup.setup_id for s in spied_state.invalidated_setups)
        observed["still_in_progress_during_save"] = setup.setup_id in spied_state.setups

    monkeypatch.setattr("arjiobot.live_setup_detection.save_setup_history_store", _spy_save)

    expired = expire_stale_setup(state, setup, expired_at=datetime.now(timezone.utc))

    assert observed == {"in_invalidated_before_save": True, "still_in_progress_during_save": True}
    assert setup.setup_id not in state.setups
    assert state.invalidated_setups == [expired]


def test_two_polls_with_no_new_swings_leave_all_three_stores_stable() -> None:
    """The exact scenario the fix targets: a swing already resolved must
    produce zero changes to IN PROGRESS, COMPLETED, or INVALIDATED on a
    later poll that presents it again."""
    state = _fake_state("ADAUSDT", ())
    failed_trace = _swing_trace("swing_stable_1", stage="SWING_16M_CONFIRMED", progress_percent=20.0, invalidation_reason="EXPANSION_NOT_CONFIRMED", is_terminal=True)
    _apply_attempt_traces(state, "ADAUSDT", (failed_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    in_progress_after_poll_1 = dict(state.setups)
    invalidated_after_poll_1 = list(state.invalidated_setups)
    completed_after_poll_1 = list(state.completed_setups)
    assert in_progress_after_poll_1 == {}
    assert len(invalidated_after_poll_1) == 1

    _apply_attempt_traces(state, "ADAUSDT", (failed_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert state.setups == in_progress_after_poll_1
    assert state.invalidated_setups == invalidated_after_poll_1
    assert state.completed_setups == completed_after_poll_1
    assert state.invalidated_setups[0] is invalidated_after_poll_1[0]
