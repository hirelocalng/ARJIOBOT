"""Model tests for Backtester."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from arjiobot.backtesting.backtest_models import (
    BacktestConfig,
    BacktestRun,
    BacktestStatus,
    SlippageConfig,
    TradeExitReason,
    TradeStatus,
    build_run_id,
    build_trade_id,
    SimulatedTrade,
)
from arjiobot.setup_tracker.setup_models import SetupDirection


def make_config() -> BacktestConfig:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return BacktestConfig(
        run_id="run",
        symbols=("btcusdt",),
        start_time=start,
        end_time=start + timedelta(days=1),
        initial_balance=Decimal("500"),
        fixed_risk_amount=Decimal("10"),
    )


def test_backtest_config_creation() -> None:
    config = make_config()

    assert config.symbols == ("BTCUSDT",)
    assert config.initial_balance == Decimal("500")
    assert config.fixed_risk_amount == Decimal("10")
    assert config.risk_per_trade == Decimal("10")
    assert config.fee_rate == Decimal("0.0006")
    assert 1 in config.timeframe_profile


def test_invalid_config_rejected() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="start_time"):
        BacktestConfig(run_id="x", symbols=("BTCUSDT",), start_time=start, end_time=start, initial_balance=Decimal("100"), fixed_risk_amount=Decimal("10"))
    with pytest.raises(ValueError, match="1M"):
        BacktestConfig(run_id="x", symbols=("BTCUSDT",), start_time=start, end_time=start + timedelta(days=1), initial_balance=Decimal("100"), fixed_risk_amount=Decimal("10"), timeframe_profile=(8, 12))
    with pytest.raises(ValueError, match="initial_balance is required"):
        BacktestConfig(run_id="x", symbols=("BTCUSDT",), start_time=start, end_time=start + timedelta(days=1), fixed_risk_amount=Decimal("10"))
    with pytest.raises(ValueError, match="fixed_risk_amount is required"):
        BacktestConfig(run_id="x", symbols=("BTCUSDT",), start_time=start, end_time=start + timedelta(days=1), initial_balance=Decimal("100"))


def test_backtest_run_and_trade_creation() -> None:
    config = make_config()
    run = BacktestRun(run_id=config.run_id, symbols=config.symbols, start_time=config.start_time, end_time=config.end_time, created_at=config.start_time, config=config)
    trade = SimulatedTrade(
        trade_id=build_trade_id("sig", config.start_time, TradeExitReason.TAKE_PROFIT),
        signal_id="sig",
        setup_id="set",
        symbol="btcusdt",
        direction=SetupDirection.BEARISH,
        entry_time=config.start_time,
        entry_price=Decimal("90"),
        stop_loss_price=Decimal("120"),
        take_profit_price=Decimal("70"),
        exit_time=config.start_time + timedelta(minutes=1),
        exit_price=Decimal("70"),
        exit_reason=TradeExitReason.TAKE_PROFIT,
        risk_amount=Decimal("100"),
        position_size=Decimal("3.33"),
        gross_pnl=Decimal("66.6"),
        fees_paid=Decimal("1"),
        slippage_paid=Decimal("0"),
        net_pnl=Decimal("65.6"),
        r_multiple=Decimal("0.656"),
        status=TradeStatus.CLOSED,
    )

    assert run.status is BacktestStatus.CREATED
    assert trade.symbol == "BTCUSDT"
    assert build_run_id(("BTCUSDT",), config.start_time, config.end_time).startswith("bt_")
    assert SlippageConfig(fixed_bps=Decimal("1")).fixed_bps == Decimal("1")
