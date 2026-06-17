"""Backtest engine tests."""

from __future__ import annotations

from arjiobot.backtesting.backtest_engine import BacktestEngine, benchmark_backtest
from arjiobot.backtesting.backtest_models import BacktestStatus
from arjiobot.backtesting.demo_backtester import build_demo_candles, build_demo_config, build_demo_signal


def test_run_backtest_and_exports() -> None:
    engine = BacktestEngine()
    run = engine.run_backtest(build_demo_config(), build_demo_candles(), signals=(build_demo_signal(),))

    assert run.status is BacktestStatus.COMPLETED
    assert run.total_trades_simulated == 1
    assert engine.get_backtest_run(run.run_id) == run
    assert "trade_id" in engine.export_trades_csv(run.run_id)
    assert "timestamp,equity" in engine.export_equity_curve_csv(run.run_id)


def test_replay_candles_filters_config_window_and_benchmark() -> None:
    engine = BacktestEngine()
    config = build_demo_config()
    candles = build_demo_candles()
    replayed = engine.replay_candles(config, candles)
    metrics = benchmark_backtest(engine, config, candles)

    assert replayed == tuple(candles)
    assert metrics["candles"] == float(len(candles))
    assert metrics["candles_per_second"] >= 0.0

