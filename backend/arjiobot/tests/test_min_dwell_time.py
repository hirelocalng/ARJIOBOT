"""Tests for the Setup Radar minimum IN PROGRESS dwell time.

Root cause this closes: a setup could be created, evaluated, and moved to
COMPLETED/INVALIDATED within the same poll cycle - the frontend (which polls
every few seconds) never gets a chance to render it in IN PROGRESS at all.
Every non-execution exit now waits at least MIN_DWELL_SECONDS since the
setup's own created_at before it actually happens; a hard execution decision
(trade_opened/rejected/risk_blocked/no_margin) always bypasses dwell.

MIN_DWELL_SECONDS/EXECUTION_TIMEOUT_SECONDS are monkeypatched down to tiny
values in these tests (instead of waiting out the real 15s/60s) - they are
plain module attributes looked up by name at call time, so patching them on
the module object is enough to change behavior without touching any other
code, which is itself one of the required tests.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import arjiobot.live_automation as live_automation
import arjiobot.live_setup_detection as live_setup_detection
from arjiobot.live_automation import (
    _expire_if_stale,
    _resolve_rejected_setup,
    _timeout_if_execution_pending_too_long,
    ensure_live_automation_state,
)
from arjiobot.live_setup_detection import _apply_attempt_traces, _setup_from_trade, move_setup_to_completed
from arjiobot.setup_tracker.setup_models import InvalidationReason, SetupState, SetupStatus


def _fake_state(symbol: str, candles=()) -> SimpleNamespace:
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
        strategy_engine=SimpleNamespace(clear_generated_signal_for_setup=lambda setup_id: None),
    )


def _swing_trace(swing_id: str, *, stage: str, progress_percent: float, invalidation_reason: str | None = None, is_terminal: bool = False, swing_timestamp: datetime | None = None) -> dict[str, object]:
    return {
        "symbol": "AAVEUSDT",
        "direction": "BULLISH",
        "swing_16m_id": swing_id,
        "swing_timestamp": (swing_timestamp or datetime.now(timezone.utc)).isoformat(),
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


def _real_trade(suffix: str, *, entry_timestamp: str | None = None) -> dict[str, object]:
    return {
        "trade_id": f"trade_{suffix}",
        "symbol": "BTCUSDT",
        "direction": "BEARISH",
        "entry_timestamp": entry_timestamp or datetime.now(timezone.utc).isoformat(),
        "entry_price": "100",
        "stop_loss": "120",
        "take_profit": "80",
        "source_12m_fvg_id": f"fvg12_{suffix}",
        "source_16m_swing_id": f"swing_{suffix}",
        "source_16m_fvg_id": f"fvg16_{suffix}",
    }


def test_strategy_failure_stays_in_in_progress_for_dwell_then_invalidates(monkeypatch) -> None:
    """For a setup that fails strategy: poll 1 appears in IN PROGRESS, stays
    there for dwell, then a later poll moves it to INVALIDATED with the
    correct reason - never within the same poll it was first observed on."""
    monkeypatch.setattr(live_setup_detection, "MIN_DWELL_SECONDS", 0.05)
    state = _fake_state("AAVEUSDT")
    trace = _swing_trace("swing_dwell_fail_1", stage="FVG_16M_CONFIRMED", progress_percent=50.0, invalidation_reason="FVG_12M_NOT_FOUND", is_terminal=True)

    _apply_attempt_traces(state, "AAVEUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    assert state.invalidated_setups == [], "must not invalidate within dwell"
    [setup] = state.setups.values()
    assert setup.current_state is SetupState.FVG_16M_CONFIRMED
    assert setup.invalidation_reason is None, "the verdict is not yet recorded on the visible setup during dwell"

    time.sleep(0.12)  # past the monkeypatched dwell window
    _apply_attempt_traces(state, "AAVEUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert state.setups == {}
    [invalidated] = state.invalidated_setups
    assert invalidated.invalidation_reason is InvalidationReason.FVG_12M_NOT_FOUND
    assert invalidated.setup_id == setup.setup_id


def test_changing_min_dwell_seconds_constant_changes_behavior(monkeypatch) -> None:
    """MIN_DWELL_SECONDS is a real, respected module constant, not a
    duplicated magic number - lowering it to 0 changes behavior immediately,
    with no other code touched."""
    monkeypatch.setattr(live_setup_detection, "MIN_DWELL_SECONDS", 0)
    state = _fake_state("AAVEUSDT")
    trace = _swing_trace("swing_dwell_zero_1", stage="FVG_16M_CONFIRMED", progress_percent=50.0, invalidation_reason="FVG_12M_NOT_FOUND", is_terminal=True)

    _apply_attempt_traces(state, "AAVEUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    [invalidated] = state.invalidated_setups
    assert invalidated.invalidation_reason is InvalidationReason.FVG_12M_NOT_FOUND


def test_no_mutation_happens_for_a_setup_during_its_dwell_period(monkeypatch) -> None:
    """During dwell, no strategy re-evaluation runs for that setup: the
    exact same object, with the exact same history, survives a second poll
    untouched - not just an equal copy, the identical object."""
    monkeypatch.setattr(live_setup_detection, "MIN_DWELL_SECONDS", 999)
    state = _fake_state("AAVEUSDT")
    trace = _swing_trace("swing_no_reeval_1", stage="FVG_16M_CONFIRMED", progress_percent=50.0, invalidation_reason="FVG_12M_NOT_FOUND", is_terminal=True)

    _apply_attempt_traces(state, "AAVEUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    [setup_after_poll_1] = list(state.setups.values())
    history_after_poll_1 = list(state.setup_history[setup_after_poll_1.setup_id])

    _apply_attempt_traces(state, "AAVEUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    [setup_after_poll_2] = list(state.setups.values())
    assert setup_after_poll_2 is setup_after_poll_1
    assert state.setup_history[setup_after_poll_1.setup_id] == history_after_poll_1


def test_staleness_gate_stays_in_in_progress_for_dwell_then_invalidates_with_staleness_expired(monkeypatch) -> None:
    """A setup whose entry zone has gone stale stays in IN PROGRESS for
    dwell before moving to INVALIDATED/staleness_expired - never within the
    same call that staleness was first confirmed."""
    monkeypatch.setattr(live_automation, "MIN_DWELL_SECONDS", 0.05)
    state = _fake_state("BTCUSDT")
    setup = _setup_from_trade(_real_trade("staleness_dwell_1"), state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    now = datetime.now(timezone.utc)
    stale_metadata = dict(setup.metadata)
    stale_metadata["detected_at_wallclock"] = (now - timedelta(minutes=30)).isoformat()
    setup = replace(setup, created_at=now, completed_at=now - timedelta(minutes=30), metadata=stale_metadata)  # already past STALE_ENTRY_READY_MAX_AGE
    state.setups[setup.setup_id] = setup
    automation = ensure_live_automation_state(state)

    result = _expire_if_stale(state, automation, setup, source="TEST")

    assert result is None, "staleness is confirmed but dwell has not elapsed yet"
    assert setup.setup_id in state.setups

    time.sleep(0.12)
    result = _expire_if_stale(state, automation, setup, source="TEST")

    assert result is not None
    assert setup.setup_id not in state.setups
    [invalidated] = state.invalidated_setups
    assert invalidated.invalidation_reason is InvalidationReason.SETUP_EXPIRED


def test_execution_timeout_moves_to_completed_when_no_response_within_timeout(monkeypatch) -> None:
    """A real ENTRY_READY setup that never gets a hard execution decision
    moves to COMPLETED tagged execution_timeout once EXECUTION_TIMEOUT_SECONDS
    elapses, instead of sitting "pending execution" forever."""
    monkeypatch.setattr(live_automation, "EXECUTION_TIMEOUT_SECONDS", 0.05)
    state = _fake_state("BTCUSDT")
    setup = _setup_from_trade(_real_trade("exec_timeout_1"), state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state.setups[setup.setup_id] = setup
    automation = ensure_live_automation_state(state)

    result = _timeout_if_execution_pending_too_long(state, automation, setup, source="TEST")
    assert result is None, "not yet timed out"
    assert setup.setup_id in state.setups

    time.sleep(0.12)
    result = _timeout_if_execution_pending_too_long(state, automation, setup, source="TEST")

    assert result is not None
    assert result["status"] == "COMPLETED"
    assert setup.setup_id not in state.setups
    [completed] = state.completed_setups
    assert completed.execution_status == "execution_timeout"


def test_execution_timeout_never_fires_for_a_setup_with_no_detection_timestamp(monkeypatch) -> None:
    """Fail-safe: a setup with no metadata["detected_at_wallclock"] (e.g.
    hand-built outside the normal detection flow) must never be timed out -
    there is no reliable wall-clock anchor to measure against."""
    monkeypatch.setattr(live_automation, "EXECUTION_TIMEOUT_SECONDS", 0.0)
    state = _fake_state("BTCUSDT")
    setup = _setup_from_trade(_real_trade("exec_timeout_no_meta"), state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    setup = replace(setup, metadata={k: v for k, v in setup.metadata.items() if k != "detected_at_wallclock"})
    state.setups[setup.setup_id] = setup
    automation = ensure_live_automation_state(state)

    result = _timeout_if_execution_pending_too_long(state, automation, setup, source="TEST")

    assert result is None
    assert setup.setup_id in state.setups


def test_hard_rejection_bypasses_dwell_even_for_a_brand_new_setup(monkeypatch) -> None:
    """Setup reaches 100%, pending execution, execution rejects before dwell
    expires - moves to COMPLETED immediately with rejected/risk_blocked/
    no_margin, regardless of how large MIN_DWELL_SECONDS is."""
    monkeypatch.setattr(live_automation, "MIN_DWELL_SECONDS", 999)
    for execution_status in ("rejected", "risk_blocked", "no_margin"):
        state = _fake_state("BTCUSDT")
        setup = _setup_from_trade(_real_trade(f"hard_{execution_status}"), state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
        state.setups[setup.setup_id] = setup

        _resolve_rejected_setup(state, setup, execution_status=execution_status, reason="test reason")

        assert setup.setup_id not in state.setups
        [completed] = state.completed_setups
        assert completed.execution_status == execution_status


def test_hard_trade_opened_bypasses_dwell_even_for_a_brand_new_setup(monkeypatch) -> None:
    """Setup reaches 100%, pending execution, execution opens the trade
    before dwell expires - moves to COMPLETED immediately with
    trade_opened, regardless of how large MIN_DWELL_SECONDS is. Exercises
    move_setup_to_completed the exact way _process_setup's success path
    does, with no dwell check anywhere in that call chain."""
    monkeypatch.setattr(live_automation, "MIN_DWELL_SECONDS", 999)
    state = _fake_state("BTCUSDT")
    setup = _setup_from_trade(_real_trade("hard_trade_opened"), state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state.setups[setup.setup_id] = setup

    move_setup_to_completed(state, replace(setup, execution_status="trade_opened", updated_at=datetime.now(timezone.utc)))

    assert setup.setup_id not in state.setups
    [completed] = state.completed_setups
    assert completed.execution_status == "trade_opened"


def test_two_setups_in_parallel_dwell_and_hard_decision_handled_independently(monkeypatch) -> None:
    """One setup hits dwell (stays in IN PROGRESS), one gets a hard
    execution decision (resolves immediately) - in the same state, at the
    same time, with zero interference between them."""
    monkeypatch.setattr(live_setup_detection, "MIN_DWELL_SECONDS", 999)
    state = _fake_state("AAVEUSDT")
    trace = _swing_trace("swing_parallel_1", stage="FVG_16M_CONFIRMED", progress_percent=50.0, invalidation_reason="FVG_12M_NOT_FOUND", is_terminal=True)
    _apply_attempt_traces(state, "AAVEUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    [dwelling] = list(state.setups.values())

    trade_trade = {**_real_trade("parallel_hard_1"), "symbol": "BTCUSDT"}
    trade_setup = _setup_from_trade(trade_trade, state=state, profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8")
    state.setups[trade_setup.setup_id] = trade_setup

    _resolve_rejected_setup(state, trade_setup, execution_status="rejected", reason="test reason")

    assert dwelling.setup_id in state.setups, "the dwelling setup must be completely unaffected by the other one's resolution"
    assert state.invalidated_setups == []
    assert trade_setup.setup_id not in state.setups
    assert any(setup.setup_id == trade_setup.setup_id and setup.execution_status == "rejected" for setup in state.completed_setups)


def test_swing_key_only_added_when_setup_finally_moves_not_during_dwell(monkeypatch) -> None:
    """Swing-key dedup must stay untouched during dwell - the permanent
    cache is only updated atomically with the COMPLETED/INVALIDATED write
    once the setup actually moves, never while it is still waiting."""
    monkeypatch.setattr(live_setup_detection, "MIN_DWELL_SECONDS", 0.05)
    state = _fake_state("AAVEUSDT")
    trace = _swing_trace("swing_dedup_during_dwell_1", stage="FVG_16M_CONFIRMED", progress_percent=50.0, invalidation_reason="FVG_12M_NOT_FOUND", is_terminal=True)

    _apply_attempt_traces(state, "AAVEUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")
    assert state.resolved_swing_keys == set(), "must not be added to the dedup cache while still dwelling"
    assert state.resolved_setup_ids == set()

    time.sleep(0.12)
    _apply_attempt_traces(state, "AAVEUSDT", (trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="MONITORING_POLL")

    assert len(state.resolved_swing_keys) == 1
    [invalidated] = state.invalidated_setups
    assert invalidated.setup_id in state.resolved_setup_ids
