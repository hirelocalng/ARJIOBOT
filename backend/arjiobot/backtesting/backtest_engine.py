"""Backtester service for deterministic historical simulation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Sequence

from arjiobot.backtesting.backtest_metrics import build_setup_conversion_analytics, calculate_metrics
from arjiobot.backtesting.backtest_models import BacktestConfig, BacktestRun, BacktestStatus, SimulatedTrade
from arjiobot.backtesting.backtest_reports import write_backtest_html_report, write_backtest_png_report
from arjiobot.backtesting.historical_replay import order_historical_candles
from arjiobot.backtesting.trade_simulator import simulate_trade
from arjiobot.market_data.candle_models import Candle
from arjiobot.strategy.strategy_models import TradeSignal


class BacktestEngine:
    """Run deterministic historical backtests."""

    def __init__(self) -> None:
        self._runs: dict[str, BacktestRun] = {}
        self._trades: dict[str, tuple[SimulatedTrade, ...]] = {}

    def run_backtest(
        self,
        config: BacktestConfig,
        historical_candles: Sequence[Candle],
        signals: Sequence[TradeSignal] = (),
    ) -> BacktestRun:
        """Run a deterministic backtest from supplied historical candles/signals."""
        ordered = order_historical_candles(historical_candles)
        trades = tuple(self.simulate_trade(signal, ordered, config) for signal in signals)
        conversion = build_setup_conversion_analytics(
            setups_created=len(signals),
            signals_generated=len(signals),
            trades=trades,
        )
        metrics = self.calculate_metrics(trades, config.initial_balance, conversion)
        run = BacktestRun(
            run_id=config.run_id,
            symbols=config.symbols,
            start_time=config.start_time,
            end_time=config.end_time,
            created_at=config.start_time,
            config=config,
            total_candles_processed=len(ordered),
            total_setups_detected=len(signals),
            total_signals_generated=len(signals),
            total_trades_simulated=len(trades),
            metrics=metrics,
            status=BacktestStatus.COMPLETED,
        )
        self._runs[run.run_id] = run
        self._trades[run.run_id] = trades
        return run

    def replay_candles(self, config: BacktestConfig, historical_candles: Sequence[Candle]) -> tuple[Candle, ...]:
        """Return validated replay order."""
        return tuple(candle for candle in order_historical_candles(historical_candles) if config.start_time <= candle.timestamp < config.end_time)

    def simulate_trade(
        self,
        signal: TradeSignal,
        future_candles: Sequence[Candle],
        config: BacktestConfig,
    ) -> SimulatedTrade:
        """Simulate one signal."""
        return simulate_trade(signal, future_candles, config)

    def calculate_metrics(
        self,
        trades: Sequence[SimulatedTrade],
        initial_balance: Decimal,
        setup_conversion: dict | None = None,
    ):
        """Calculate metrics."""
        return calculate_metrics(trades, initial_balance=initial_balance, setup_conversion=setup_conversion)

    def get_backtest_run(self, run_id: str) -> BacktestRun | None:
        return self._runs.get(run_id)

    def get_backtest_report(self, run_id: str) -> dict[str, str] | None:
        run = self._runs.get(run_id)
        return run.reports if run else None

    def export_trades_csv(self, run_id: str) -> str:
        """Export trades as CSV text."""
        rows = ["trade_id,signal_id,symbol,entry_time,exit_time,net_pnl,status"]
        for trade in self._trades.get(run_id, ()):
            rows.append(f"{trade.trade_id},{trade.signal_id},{trade.symbol},{trade.entry_time},{trade.exit_time},{trade.net_pnl},{trade.status.value}")
        return "\n".join(rows)

    def export_equity_curve_csv(self, run_id: str) -> str:
        """Export equity curve as CSV text."""
        run = self._runs[run_id]
        rows = ["timestamp,equity"]
        if run.metrics:
            rows.extend(f"{timestamp},{equity}" for timestamp, equity in run.metrics.equity_curve)
        return "\n".join(rows)

    def write_reports(self, run_id: str, report_dir: Path) -> BacktestRun:
        """Write HTML/PNG reports for a run."""
        run = self._runs[run_id]
        trades = self._trades.get(run_id, ())
        if run.metrics is None:
            raise ValueError("run metrics are required")
        html = report_dir / "backtest_validation_report.html"
        png = report_dir / "backtest_validation_report.png"
        summary = {
            "total_trades": run.metrics.total_trades,
            "wins": run.metrics.wins,
            "losses": run.metrics.losses,
            "net_profit": str(run.metrics.net_profit),
            "ending_balance": str(run.metrics.ending_balance),
        }
        write_backtest_html_report(
            path=html,
            summary=summary,
            trades=trades,
            metrics=run.metrics,
            known_limitations=(
                "v1 simulates bearish Strategy Engine signals only.",
                "v1 does not call Bitget or place live orders.",
                "v1 sequentially processes multi-symbol inputs.",
            ),
        )
        write_backtest_png_report(path=png, metrics=run.metrics)
        updated = replace(run, reports={"html": str(html), "png": str(png)})
        self._runs[run_id] = updated
        return updated


def benchmark_backtest(engine: BacktestEngine, config: BacktestConfig, candles: Sequence[Candle]) -> dict[str, float]:
    """Benchmark replay ordering."""
    started_at = perf_counter()
    ordered = engine.replay_candles(config, candles)
    elapsed_ms = (perf_counter() - started_at) * 1000
    return {
        "candles": float(len(ordered)),
        "duration_ms": elapsed_ms,
        "candles_per_second": (len(ordered) / (elapsed_ms / 1000)) if elapsed_ms else 0.0,
    }
