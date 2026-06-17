"""Metrics tests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.backtesting.backtest_metrics import build_equity_curve, build_setup_conversion_analytics, calculate_max_drawdown, calculate_metrics
from arjiobot.backtesting.demo_backtester import build_demo_candles, build_demo_config, build_demo_signal
from arjiobot.backtesting.trade_simulator import simulate_trade


def test_equity_curve_drawdown_and_metrics() -> None:
    trade = simulate_trade(build_demo_signal(), build_demo_candles(), build_demo_config())
    curve = build_equity_curve(Decimal("10000"), [trade])
    drawdown, drawdown_pct = calculate_max_drawdown(curve, Decimal("10000"))
    metrics = calculate_metrics([trade], initial_balance=Decimal("10000"))

    assert curve
    assert drawdown >= Decimal("0")
    assert drawdown_pct >= 0.0
    assert metrics.total_trades == 1
    assert metrics.wins == 1
    assert metrics.profit_factor == float("inf")
    assert metrics.ending_balance > Decimal("10000")


def test_setup_conversion_analytics() -> None:
    trade = simulate_trade(build_demo_signal(), build_demo_candles(), build_demo_config())
    analytics = build_setup_conversion_analytics(setups_created=1, signals_generated=1, trades=[trade])

    assert analytics["setups_created"] == 1
    assert analytics["trades_entered"] == 1
    assert analytics["trades_won"] == 1

