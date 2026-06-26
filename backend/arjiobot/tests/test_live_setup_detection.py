"""Tests for live candle-to-setup detection helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import arjiobot.live_setup_detection as live_setup_detection
from arjiobot.backtesting.historical_replay import load_ohlcv_csv
from arjiobot.backtesting.research_profiles import PROFILE_2
from arjiobot.backtesting.timeframe_profiles import get_timeframe_profile
from arjiobot.live_setup_detection import _runner, _setup_from_trade, candles_from_bitget_rows, detect_live_setups_for_symbol
from arjiobot.strategy.strategy_engine import StrategyEngine
from arjiobot.strategy.strategy_models import SignalStatus

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


def test_direct_12m_retrace_live_trade_candidate_becomes_valid_signal() -> None:
    trade = {
        "trade_id": "trade_live_1",
        "symbol": "BTCUSDT",
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

    setup = _setup_from_trade(trade, state=_fake_state("BTCUSDT", ()), profile_id="PROFILE_2", timeframe_profile_id="PROFILE_15_10_5")
    signal = StrategyEngine().generate_signal_from_setup(setup)

    assert setup.metadata["entry_model"] == "DIRECT_12M_RETRACE"
    assert setup.one_minute_swing_id is None
    assert signal.status is SignalStatus.GENERATED
    assert signal.entry_reference_price == 100
    assert signal.stop_reference_price == 120
    assert signal.final_target_price == 80


def test_bitget_rows_are_normalized_to_closed_one_minute_candles() -> None:
    base = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=3)
    rows = (
        (str(int(base.timestamp() * 1000)), "10", "12", "9", "11", "100"),
        (str(int((base + timedelta(minutes=1)).timestamp() * 1000)), "11", "13", "10", "12", "110"),
    )

    candles = candles_from_bitget_rows("ETHUSDT", rows)

    assert len(candles) == 2
    assert candles[0].symbol == "ETHUSDT"
    assert candles[0].timeframe.minutes == 1
    assert candles[1].close == 12


def test_bitget_rows_keep_latest_incomplete_one_minute_candle() -> None:
    current = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    closed = current - timedelta(minutes=1)
    rows = (
        (str(int(closed.timestamp() * 1000)), "10", "12", "9", "11", "100"),
        (str(int(current.timestamp() * 1000)), "11", "13", "10", "12", "110"),
    )

    candles = candles_from_bitget_rows("ETHUSDT", rows)

    assert len(candles) == 2
    assert candles[-1].timestamp == current
    assert candles[-1].metadata["source_status"] == "INCOMPLETE_LATEST_1M"


def test_live_detector_loads_real_profile_evaluator() -> None:
    runner = _runner()

    assert hasattr(runner, "_build_strategy_funnel")
    assert hasattr(runner, "_research_expansions")


def test_saved_timeframe_setting_overrides_profile_builtin_default(monkeypatch) -> None:
    """The saved live setting (state.settings['default_timeframe_profile']) must win
    over the active profile's built-in timeframe_profile_id - an operator's explicit
    live-trading choice must not be silently overridden by a profile default.

    PROFILE_2's own built-in timeframe_profile_id is DEFAULT_16_12_8 (it always
    follows the 16M/12M/8M stack - see research_profiles.py), so this test sets a
    *different* saved value (PROFILE_15_10_5) and proves that one wins, which
    proves the precedence order itself rather than a value that happens to agree
    with the built-in default either way.
    """
    assert PROFILE_2.timeframe_profile_id == "DEFAULT_16_12_8"

    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])
    state.settings["default_timeframe_profile"] = "PROFILE_15_10_5"

    resolved_profile_ids: list[str] = []

    def recording_get_timeframe_profile(profile_id):
        resolved = get_timeframe_profile(profile_id)
        resolved_profile_ids.append(resolved.profile_id)
        return resolved

    monkeypatch.setattr(live_setup_detection, "get_timeframe_profile", recording_get_timeframe_profile)

    detect_live_setups_for_symbol(state, "ADAUSDT")

    assert resolved_profile_ids == ["PROFILE_15_10_5"]


def test_bearish_funnel_failure_does_not_block_bullish_detection(monkeypatch) -> None:
    """A bug in either direction's funnel must never take down the other - in
    particular, a problem in the newer bullish path must never degrade the
    proven bearish path's ability to keep taking trades, and vice versa."""
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])
    runner = _runner()
    monkeypatch.setattr(runner, "_build_strategy_funnel", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated bearish funnel bug")))

    result = detect_live_setups_for_symbol(state, "ADAUSDT")

    assert result["status"] != "ERROR"
    latest_funnel = state.live_setup_detection["latest_funnel"]["ADAUSDT"]
    assert "error" in latest_funnel["bearish"]
    assert "error" not in latest_funnel["bullish"]
    assert "passed_expansion" in latest_funnel["bullish"]


def test_bullish_funnel_failure_does_not_block_bearish_detection(monkeypatch) -> None:
    candles_1m = load_ohlcv_csv(DATA_DIR / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state = _fake_state("ADAUSDT", candles_1m[:5000])
    runner = _runner()
    monkeypatch.setattr(runner, "_build_bullish_strategy_funnel", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated bullish funnel bug")))

    result = detect_live_setups_for_symbol(state, "ADAUSDT")

    assert result["status"] != "ERROR"
    latest_funnel = state.live_setup_detection["latest_funnel"]["ADAUSDT"]
    assert "error" in latest_funnel["bullish"]
    assert "error" not in latest_funnel["bearish"]
    assert "passed_expansion" in latest_funnel["bearish"]
