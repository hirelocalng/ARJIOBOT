"""Metrics engine for deterministic backtests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from arjiobot.backtesting.backtest_models import BacktestMetrics, SimulatedTrade, TradeExitReason, TradeStatus


def build_equity_curve(initial_balance: Decimal, trades: Sequence[SimulatedTrade]) -> tuple[tuple[datetime, Decimal], ...]:
    """Build equity curve from closed trades."""
    balance = initial_balance
    curve: list[tuple[datetime, Decimal]] = []
    for trade in trades:
        if trade.exit_time is None:
            continue
        balance += trade.net_pnl
        curve.append((trade.exit_time, balance))
    return tuple(curve)


def calculate_max_drawdown(equity_curve: Sequence[tuple[datetime, Decimal]], initial_balance: Decimal) -> tuple[Decimal, float]:
    """Calculate max drawdown and percent."""
    peak = initial_balance
    max_dd = Decimal("0")
    for _, equity in equity_curve:
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_dd:
            max_dd = drawdown
    pct = float(max_dd / peak * Decimal("100")) if peak else 0.0
    return max_dd, pct


def calculate_metrics(
    trades: Sequence[SimulatedTrade],
    *,
    initial_balance: Decimal,
    setup_conversion: dict | None = None,
) -> BacktestMetrics:
    """Calculate required metrics."""
    entered = [trade for trade in trades if trade.entry_time is not None]
    wins = [trade for trade in entered if trade.exit_reason is TradeExitReason.TAKE_PROFIT]
    losses = [trade for trade in entered if trade.exit_reason is TradeExitReason.STOP_LOSS]
    skipped = [trade for trade in trades if trade.status.name.startswith("SKIPPED")]
    ambiguous = [trade for trade in trades if trade.status is TradeStatus.AMBIGUOUS]
    gross_profit = sum((trade.gross_pnl for trade in wins), Decimal("0"))
    gross_loss = sum((trade.gross_pnl for trade in losses), Decimal("0"))
    net_profit = sum((trade.net_pnl for trade in trades), Decimal("0"))
    win_rate = len(wins) / len(entered) * 100 if entered else 0.0
    profit_factor = float(gross_profit / abs(gross_loss)) if gross_loss else (float("inf") if gross_profit > 0 else 0.0)
    average_r = float(sum((trade.r_multiple for trade in entered), Decimal("0")) / len(entered)) if entered else 0.0
    expectancy = float(net_profit / len(entered)) if entered else 0.0
    curve = build_equity_curve(initial_balance, trades)
    max_dd, max_dd_pct = calculate_max_drawdown(curve, initial_balance)
    winning_net = [trade.net_pnl for trade in wins]
    losing_net = [trade.net_pnl for trade in losses]
    ending_balance = curve[-1][1] if curve else initial_balance
    return BacktestMetrics(
        total_trades=len(entered),
        wins=len(wins),
        losses=len(losses),
        skipped_trades=len(skipped),
        ambiguous_trades=len(ambiguous),
        win_rate=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net_profit,
        profit_factor=profit_factor,
        average_r=average_r,
        expectancy=expectancy,
        max_drawdown=max_dd,
        max_drawdown_percent=max_dd_pct,
        ending_balance=ending_balance,
        equity_curve=curve,
        largest_win=max(winning_net) if winning_net else Decimal("0"),
        largest_loss=min(losing_net) if losing_net else Decimal("0"),
        average_win=sum(winning_net, Decimal("0")) / len(winning_net) if winning_net else Decimal("0"),
        average_loss=sum(losing_net, Decimal("0")) / len(losing_net) if losing_net else Decimal("0"),
        setup_conversion=setup_conversion or {},
    )


def build_setup_conversion_analytics(*, setups_created: int, signals_generated: int, trades: Sequence[SimulatedTrade]) -> dict:
    """Build setup conversion analytics for dashboard use."""
    return {
        "setups_created": setups_created,
        "setups_reaching_30_percent": setups_created,
        "setups_reaching_50_percent": setups_created,
        "setups_reaching_70_percent": signals_generated,
        "setups_reaching_90_percent": signals_generated,
        "setups_reaching_entry_ready": signals_generated,
        "signals_generated": signals_generated,
        "trades_entered": len([trade for trade in trades if trade.entry_time is not None]),
        "trades_won": len([trade for trade in trades if trade.exit_reason is TradeExitReason.TAKE_PROFIT]),
        "trades_lost": len([trade for trade in trades if trade.exit_reason is TradeExitReason.STOP_LOSS]),
        "invalidation_reason_counts": {},
        "most_common_failure_stage": None,
    }
