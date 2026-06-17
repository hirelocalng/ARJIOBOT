"""Trade simulation for Strategy Engine signals."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from arjiobot.backtesting.backtest_models import (
    BacktestConfig,
    SameCandleResolutionPolicy,
    SimulatedTrade,
    TradeExitReason,
    TradeStatus,
    build_trade_id,
)
from arjiobot.backtesting.fees import calculate_fees
from arjiobot.backtesting.slippage import (
    apply_bearish_entry_slippage,
    apply_bearish_exit_slippage,
    calculate_slippage_paid,
)
from arjiobot.market_data.candle_models import Candle
from arjiobot.risk.rr_profiles import calculate_fixed_risk_trade_math, calculate_pnl
from arjiobot.setup_tracker.setup_models import SetupDirection
from arjiobot.strategy.strategy_models import SignalAction, TradeSignal


def calculate_position_size(*, risk_amount, entry_price, stop_loss_price) -> Decimal:
    """Simplified risk sizing for simulation only."""
    risk = Decimal(str(risk_amount))
    distance = abs(Decimal(str(stop_loss_price)) - Decimal(str(entry_price)))
    if distance <= Decimal("0"):
        raise ValueError("stop distance must be positive")
    return risk / distance


def calculate_r_multiple(net_pnl, risk_amount) -> Decimal:
    """Return R multiple."""
    risk = Decimal(str(risk_amount))
    return Decimal(str(net_pnl)) / risk if risk else Decimal("0")


def simulate_trade(signal: TradeSignal, future_candles: Sequence[Candle], config: BacktestConfig) -> SimulatedTrade:
    """Simulate one bearish market-sell signal."""
    if signal.action is not SignalAction.MARKET_SELL_READY:
        raise ValueError("v1 backtester supports MARKET_SELL_READY only")
    ordered = tuple(sorted(future_candles, key=lambda candle: candle.timestamp))
    if signal.stop_reference_price is None:
        raise ValueError("signal stop reference is required")

    entry_candidates = [candle for candle in ordered if candle.timestamp > signal.generated_at]
    if not entry_candidates:
        return _skipped_trade(signal, TradeExitReason.NO_ENTRY_CANDLE, TradeStatus.SKIPPED_NO_ENTRY_CANDLE, config)
    entry_candle = entry_candidates[0]
    raw_entry = entry_candle.open
    entry_price = apply_bearish_entry_slippage(raw_entry, config.slippage_model.fixed_bps)
    rr_math = calculate_fixed_risk_trade_math(
        direction=SetupDirection.BEARISH,
        entry=entry_price,
        stop_loss=signal.stop_reference_price,
        fixed_risk_amount=config.risk_per_trade,
        selected_rr_profile=getattr(config, "selected_rr_profile", "RR_1_5"),
    )
    position_size = rr_math.position_size
    take_profit_price = rr_math.take_profit
    pre_entry = [candle for candle in ordered if signal.generated_at <= candle.timestamp < entry_candle.timestamp]
    if any(candle.low <= take_profit_price for candle in pre_entry):
        return _skipped_trade(signal, TradeExitReason.TARGET_ALREADY_REACHED, TradeStatus.SKIPPED_TARGET_ALREADY_REACHED, config)

    exit_time = None
    raw_exit = None
    exit_reason = TradeExitReason.END_OF_DATA
    status = TradeStatus.OPEN
    for candle in entry_candidates:
        stop_hit = candle.high >= signal.stop_reference_price
        target_hit = candle.low <= take_profit_price
        if stop_hit and target_hit:
            policy = config.same_candle_resolution_policy
            if policy is SameCandleResolutionPolicy.CONSERVATIVE_STOP_FIRST:
                raw_exit = signal.stop_reference_price
                exit_reason = TradeExitReason.STOP_LOSS
                status = TradeStatus.CLOSED
            elif policy is SameCandleResolutionPolicy.OPTIMISTIC_TP_FIRST:
                raw_exit = take_profit_price
                exit_reason = TradeExitReason.TAKE_PROFIT
                status = TradeStatus.CLOSED
            elif policy is SameCandleResolutionPolicy.SKIP_TRADE:
                return _skipped_trade(signal, TradeExitReason.AMBIGUOUS, TradeStatus.AMBIGUOUS, config)
            else:
                raw_exit = candle.close
                exit_reason = TradeExitReason.AMBIGUOUS
                status = TradeStatus.AMBIGUOUS
            exit_time = candle.end_timestamp
            break
        if stop_hit:
            raw_exit = signal.stop_reference_price
            exit_reason = TradeExitReason.STOP_LOSS
            status = TradeStatus.CLOSED
            exit_time = candle.end_timestamp
            break
        if target_hit:
            raw_exit = take_profit_price
            exit_reason = TradeExitReason.TAKE_PROFIT
            status = TradeStatus.CLOSED
            exit_time = candle.end_timestamp
            break

    if raw_exit is None:
        raw_exit = entry_candidates[-1].close
        exit_time = entry_candidates[-1].end_timestamp

    exit_price = apply_bearish_exit_slippage(raw_exit, config.slippage_model.fixed_bps)
    gross_pnl = calculate_pnl(direction=SetupDirection.BEARISH, entry_price=entry_price, exit_price=exit_price, position_size=position_size)
    fees = calculate_fees(
        entry_price=entry_price,
        exit_price=exit_price,
        position_size=position_size,
        fee_rate=config.fee_rate,
    )
    slippage_paid = calculate_slippage_paid(
        raw_entry=raw_entry,
        adjusted_entry=entry_price,
        raw_exit=raw_exit,
        adjusted_exit=exit_price,
        position_size=position_size,
    )
    net_pnl = gross_pnl - fees
    r_multiple = calculate_r_multiple(net_pnl, config.risk_per_trade)
    return SimulatedTrade(
        trade_id=build_trade_id(signal.signal_id, entry_candle.timestamp, exit_reason),
        signal_id=signal.signal_id,
        setup_id=signal.setup_id,
        symbol=signal.symbol,
        direction=SetupDirection.BEARISH,
        entry_time=entry_candle.timestamp,
        entry_price=entry_price,
        stop_loss_price=signal.stop_reference_price,
        take_profit_price=take_profit_price,
        exit_time=exit_time,
        exit_price=exit_price,
        exit_reason=exit_reason,
        risk_amount=rr_math.fixed_risk_amount,
        position_size=position_size,
        gross_pnl=gross_pnl,
        fees_paid=fees,
        slippage_paid=slippage_paid,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
        status=status,
        metadata={
            "fixed_risk_amount": str(rr_math.fixed_risk_amount),
            "selected_rr_profile": rr_math.selected_rr_profile,
            "selected_rr_value": str(rr_math.selected_rr_value),
            "target_reward_amount": str(rr_math.target_reward_amount),
            "actual_risk_amount": str(rr_math.actual_risk_amount),
            "expected_reward_amount": str(rr_math.expected_reward_amount),
            "actual_rr": str(rr_math.actual_rr),
        },
    )


def _skipped_trade(
    signal: TradeSignal,
    reason: TradeExitReason,
    status: TradeStatus,
    config: BacktestConfig,
) -> SimulatedTrade:
    return SimulatedTrade(
        trade_id=build_trade_id(signal.signal_id, None, reason),
        signal_id=signal.signal_id,
        setup_id=signal.setup_id,
        symbol=signal.symbol,
        direction=SetupDirection.BEARISH,
        entry_time=None,
        entry_price=None,
        stop_loss_price=signal.stop_reference_price or Decimal("0"),
        take_profit_price=signal.final_target_price or Decimal("0"),
        exit_time=None,
        exit_price=None,
        exit_reason=reason,
        risk_amount=config.risk_per_trade,
        position_size=Decimal("0"),
        gross_pnl=Decimal("0"),
        fees_paid=Decimal("0"),
        slippage_paid=Decimal("0"),
        net_pnl=Decimal("0"),
        r_multiple=Decimal("0"),
        status=status,
    )
