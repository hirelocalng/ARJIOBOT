"""Tests for live candle-to-setup detection helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arjiobot.live_setup_detection import _runner, _setup_from_trade, candles_from_bitget_rows
from arjiobot.strategy.strategy_engine import StrategyEngine
from arjiobot.strategy.strategy_models import SignalStatus


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

    setup = _setup_from_trade(trade, profile_id="PROFILE_2", timeframe_profile_id="PROFILE_15_10_5")
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


def test_live_detector_loads_real_profile_evaluator() -> None:
    runner = _runner()

    assert hasattr(runner, "_build_strategy_funnel")
    assert hasattr(runner, "_research_expansions")
