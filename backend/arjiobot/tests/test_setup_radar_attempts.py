"""Tests for the Setup Radar live attempt tracker.

These prove the radar is a real setup-attempt tracker, not just an ENTRY_READY
trade log: every swing candidate becomes a visible, symbol-tagged attempt that
progresses or is invalidated through the chain, capped at the latest 100.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.backtesting.historical_replay import load_ohlcv_csv
from arjiobot.exchange.bitget_environment import BitgetCredentialConfig, TradeMode
from arjiobot.live_automation import run_live_automation_once
from arjiobot.live_setup_detection import _apply_attempt_traces, _setup_from_trade, detect_live_setups_for_symbol
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
        setup_history={},
        live_setup_detection={"processed_trade_keys": []},
    )


def test_swing_only_attempt_is_logged_and_visible_with_its_symbol() -> None:
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])

    detect_live_setups_for_symbol(state, "ADAUSDT")

    assert state.setups, "expected at least one tracked setup attempt"
    # Critical display requirement: every attempt, at every stage, carries its symbol.
    assert all(setup.symbol == "ADAUSDT" for setup in state.setups.values())
    assert any(setup.swing_16m_id for setup in state.setups.values())
    # At minimum, attempts should exist at or beyond the swing stage (20%).
    assert all(setup.progress_percent >= 20.0 for setup in state.setups.values())


def test_failed_expansion_attempt_is_retained_with_invalidation_reason() -> None:
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])

    detect_live_setups_for_symbol(state, "ADAUSDT")

    expansion_failures = [
        setup
        for setup in state.setups.values()
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


def test_only_latest_100_attempts_are_retained() -> None:
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:6000])
    detect_live_setups_for_symbol(state, "ADAUSDT")
    assert len(state.setups) <= 100

    # Keep extending the live candle window (more polls, more swing candidates)
    # until the cap is exercised.
    for end in range(6000, len(candles_1m), 1000):
        state.live_candles["ADAUSDT"] = candles_1m[:end]
        detect_live_setups_for_symbol(state, "ADAUSDT")
        assert len(state.setups) <= 100, f"100-cap violated with {len(state.setups)} tracked setups"
        if len(state.setups) == 100:
            break
    else:
        raise AssertionError("expected enough swing candidates across this fixture to exercise the 100-cap")

    assert all(setup.symbol == "ADAUSDT" for setup in state.setups.values())


def test_eviction_never_removes_a_pending_entry_ready_setup() -> None:
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])
    detect_live_setups_for_symbol(state, "ADAUSDT")

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

    for end in range(5000, len(candles_1m), 1000):
        state.live_candles["ADAUSDT"] = candles_1m[:end]
        detect_live_setups_for_symbol(state, "ADAUSDT")
        if len(state.setups) >= 100:
            break

    assert pending.setup_id in state.setups, "an ENTRY_READY setup must never be evicted by the attempt cap"
    assert state.setups[pending.setup_id].status is SetupStatus.ENTRY_READY


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
    [setup] = state.setups.values()
    assert setup.status is SetupStatus.INVALIDATED
    assert setup.invalidation_reason is InvalidationReason.EXPANSION_NOT_CONFIRMED
    assert setup.invalidated_at is not None

    resolved_trace = {**base_trace, "stage": "ENTRY_READY", "progress_percent": 100.0, "invalidation_reason": None, "is_terminal": True}
    _apply_attempt_traces(state, "ADAUSDT", (resolved_trace,), profile_id="PROFILE_2", timeframe_profile_id="DEFAULT_16_12_8", selected_tp_model="", source="LIVE_MARKET_DATA")
    [setup] = state.setups.values()
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

    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    detection_state = SimpleNamespace(
        live_candles={"ADAUSDT": candles_1m[:5000]},
        settings=state.settings,
        setups=state.setups,
        setup_history=state.setup_history,
        live_setup_detection={"processed_trade_keys": []},
    )
    detect_live_setups_for_symbol(detection_state, "ADAUSDT")
    assert state.setups, "expected attempt rows to exist"
    assert not any(setup.current_state is SetupState.ENTRY_READY for setup in state.setups.values()), (
        "fixture assumption: no real ENTRY_READY trade in this window, only attempt traces"
    )

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "WAITING"
    assert result["reason"] == "No ENTRY_READY setup found."
    assert state.bitget_environment.orders == []
