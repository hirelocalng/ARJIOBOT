"""Trade simulator tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from arjiobot.backtesting.backtest_models import SameCandleResolutionPolicy, TradeExitReason, TradeStatus
from arjiobot.backtesting.demo_backtester import build_demo_candles, build_demo_config, build_demo_signal, make_candle
from arjiobot.backtesting.trade_simulator import calculate_position_size, calculate_r_multiple, simulate_trade


def test_entry_at_next_1m_candle_open_and_take_profit() -> None:
    signal = build_demo_signal()
    trade = simulate_trade(signal, build_demo_candles(), build_demo_config())

    assert trade.entry_time == build_demo_candles()[1].timestamp
    assert trade.entry_price == build_demo_candles()[1].open
    assert trade.exit_reason is TradeExitReason.TAKE_PROFIT
    assert trade.status is TradeStatus.CLOSED


def test_bearish_stop_loss_hit() -> None:
    signal = build_demo_signal()
    candles = [
        make_candle(0, open_="95", high="96", low="90", close="92"),
        make_candle(1, open_="90", high="121", low="84", close="120"),
    ]
    trade = simulate_trade(signal, candles, build_demo_config())

    assert trade.exit_reason is TradeExitReason.STOP_LOSS


def test_target_already_reached_before_entry() -> None:
    signal = build_demo_signal()
    candles = [
        make_candle(0, open_="95", high="96", low="44", close="46"),
        make_candle(1, open_="90", high="92", low="84", close="86"),
    ]
    trade = simulate_trade(signal, candles, build_demo_config())

    assert trade.status is TradeStatus.SKIPPED_TARGET_ALREADY_REACHED


def test_same_candle_conservative_policy() -> None:
    signal = build_demo_signal()
    candles = [
        make_candle(0, open_="95", high="96", low="90", close="92"),
        make_candle(1, open_="90", high="121", low="44", close="80"),
    ]
    trade = simulate_trade(signal, candles, build_demo_config())

    assert trade.exit_reason is TradeExitReason.STOP_LOSS


def test_same_candle_skip_policy() -> None:
    signal = build_demo_signal()
    config = replace(build_demo_config(), same_candle_resolution_policy=SameCandleResolutionPolicy.SKIP_TRADE)
    candles = [
        make_candle(0, open_="95", high="96", low="90", close="92"),
        make_candle(1, open_="90", high="121", low="44", close="80"),
    ]
    trade = simulate_trade(signal, candles, config)

    assert trade.status is TradeStatus.AMBIGUOUS


def test_position_size_and_r_multiple() -> None:
    assert calculate_position_size(risk_amount=100, entry_price=90, stop_loss_price=120) == Decimal("3.333333333333333333333333333")
    assert calculate_r_multiple(Decimal("50"), Decimal("100")) == Decimal("0.5")
