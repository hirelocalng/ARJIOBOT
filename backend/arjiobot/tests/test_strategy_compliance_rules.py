"""Strategy compliance tests for exact ArjioBot rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arjiobot.backtesting.backtest_models import BacktestConfig, SameCandleResolutionPolicy, TradeExitReason, build_run_id
from arjiobot.backtesting.trade_simulator import simulate_trade
from arjiobot.expansion.expansion import ExpansionDetectionEngine
from arjiobot.fvg.fvg import FVGDetectionEngine
from arjiobot.fvg.fvg_models import FVGDirection
from arjiobot.fvg.fvg_tap_rules import fvg_inside_bearish_leg
from arjiobot.market_data.candle_models import Candle, Timeframe
from arjiobot.risk.demo_risk import default_context, make_signal
from arjiobot.risk.risk_engine import RiskEngine
from arjiobot.setup_tracker.demo_setup_tracker import make_fvg
from arjiobot.setup_tracker.setup_models import InvalidationReason, SetupState
from arjiobot.setup_tracker.setup_tracker import SetupTracker
from arjiobot.strategy.demo_strategy import make_entry_ready_setup
from arjiobot.strategy.strategy_engine import StrategyEngine
from arjiobot.swings.swings import SwingDetectionEngine


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def candle(index: int, open_: str, high: str, low: str, close: str, timeframe: int = 1) -> Candle:
    return Candle(symbol="BTCUSDT", timeframe=Timeframe(timeframe), timestamp=BASE + timedelta(minutes=index * timeframe), open=open_, high=high, low=low, close=close, volume="10")


def test_strict_swings_and_fvg_equality_rejections() -> None:
    swings = SwingDetectionEngine().detect_all_swings([candle(0, "1", "2", "1", "1"), candle(1, "1", "3", "1", "2"), candle(2, "2", "2", "1", "1")])
    equal_swings = SwingDetectionEngine().detect_all_swings([candle(0, "1", "3", "1", "1"), candle(1, "1", "3", "1", "2"), candle(2, "2", "2", "1", "1")])
    lows = SwingDetectionEngine().detect_all_swings([candle(0, "3", "4", "2", "3"), candle(1, "3", "4", "1", "2"), candle(2, "2", "4", "2", "3")])
    fvg = FVGDetectionEngine().detect_fvgs([candle(0, "10", "12", "10", "11"), candle(1, "11", "12", "10", "10"), candle(2, "8", "9", "7", "8")])
    equal_fvg = FVGDetectionEngine().detect_fvgs([candle(0, "10", "12", "9", "11"), candle(1, "11", "12", "10", "10"), candle(2, "8", "9", "7", "8")])

    assert len(swings.swing_highs) == 1
    assert not equal_swings.swing_highs
    assert len(lows.swing_lows) == 1
    assert len(fvg.fvgs) == 1 and fvg.fvgs[0].direction is FVGDirection.BEARISH
    assert not equal_fvg.fvgs


def test_expansion_ratio_boundaries() -> None:
    base = [candle(0, "10", "12", "10", "11"), candle(1, "11", "15", "10", "12"), candle(2, "12", "13", "6", "6")]
    swing = SwingDetectionEngine().detect_all_swings(base).swing_highs[0]
    assert ExpansionDetectionEngine().detect_from_swing(swing) is not None

    below = SwingDetectionEngine().detect_all_swings([candle(0, "10", "12", "10", "11"), candle(1, "11", "15", "10", "12"), candle(2, "12", "13", "10", "10")]).swing_highs[0]
    above = SwingDetectionEngine().detect_all_swings([candle(0, "10", "12", "10", "11"), candle(1, "11", "15", "10", "12"), candle(2, "12", "14", "-1", "-1")]).swing_highs[0]
    assert ExpansionDetectionEngine().detect_from_swing(below) is None
    assert ExpansionDetectionEngine().detect_from_swing(above) is None


def test_setup_invalidation_rules_and_leg_checks() -> None:
    fvg = make_fvg(fvg_id="fvg12", timeframe_minutes=12, upper="100", lower="90", confirmed_index=0)
    outside = make_fvg(fvg_id="out", timeframe_minutes=12, upper="80", lower="70", confirmed_index=0)
    assert fvg_inside_bearish_leg(fvg=fvg, swing_high_price=Decimal("110"), completion_candle_low=Decimal("85"))
    assert not fvg_inside_bearish_leg(fvg=outside, swing_high_price=Decimal("110"), completion_candle_low=Decimal("85"))

    tracker = SetupTracker()
    setup = tracker.create_setup(symbol="BTCUSDT", created_at=BASE, htf_fvg_id="htf")
    late = tracker.process_retrace_window(setup.setup_id, fvg_12m=fvg, candles_8m=[candle(i, "70", "80", "60", "70", 8) for i in range(3)])
    assert late.invalidation_reason is InvalidationReason.RETRACE_WINDOW_EXPIRED

    setup = tracker.create_setup(symbol="ETHUSDT", created_at=BASE, htf_fvg_id="htf2")
    close_above = tracker.process_one_minute_confirmation(setup.setup_id, fvg_12m=fvg, candles_1m=[candle(0, "95", "101", "94", "101")])
    assert close_above.invalidation_reason is InvalidationReason.CLOSE_ABOVE_12M_FVG

    setup = tracker.create_setup(symbol="SOLUSDT", created_at=BASE, htf_fvg_id="htf3")
    third = tracker.process_one_minute_confirmation(setup.setup_id, fvg_12m=fvg, candles_1m=[candle(0, "91", "92", "90", "90"), candle(1, "92", "94", "90", "90"), candle(2, "94", "96", "90", "90")])
    assert third.invalidation_reason is InvalidationReason.THIRD_HIGH_INSIDE_12M_FVG


def test_strategy_risk_execution_and_backtest_safety_rules() -> None:
    setup = make_entry_ready_setup()
    signal = StrategyEngine().generate_signal_from_setup(setup)
    non_ready = replace(setup, current_state=SetupState.WATCHING_HTF_FVG)
    rejected = StrategyEngine().generate_signal_from_setup(non_ready)
    assert signal.action.value == "MARKET_SELL_READY"
    assert rejected.status.value == "REJECTED"

    config, snapshot, state = default_context()
    plan = RiskEngine().create_trade_plan(make_signal(), config, snapshot, state)
    assert plan.stop_loss_price == make_signal().stop_reference_price
    assert plan.take_profit_price == Decimal("45.0")

    entry = Candle(symbol="BTCUSDT", timeframe=Timeframe(1), timestamp=signal.generated_at + timedelta(minutes=1), open="90", high="121", low="60", close="90", volume="10")
    candles = [entry]
    bt_config = BacktestConfig(run_id=build_run_id(("BTCUSDT",), BASE, BASE + timedelta(minutes=20)), symbols=("BTCUSDT",), start_time=BASE, end_time=BASE + timedelta(minutes=20), initial_balance=Decimal("10000"), fixed_risk_amount=Decimal("100"), same_candle_resolution_policy=SameCandleResolutionPolicy.CONSERVATIVE_STOP_FIRST)
    trade = simulate_trade(signal, candles, bt_config)
    assert trade.entry_price == entry.open
    assert trade.exit_reason is TradeExitReason.STOP_LOSS
