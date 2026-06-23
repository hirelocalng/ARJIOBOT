"""Signal risk validation."""

from __future__ import annotations

import logging
from decimal import ROUND_FLOOR, Decimal

from arjiobot.market_data.candle_models import to_decimal
from arjiobot.risk.exposure import exposure_after_trade, has_same_symbol_exposure
from arjiobot.risk.isolated_margin import DEFAULT_FEE_RATE, DEFAULT_SLIPPAGE_BUFFER_RATE, calculate_required_margin
from arjiobot.risk.loss_limits import daily_loss_capacity_remaining, weekly_loss_capacity_remaining
from arjiobot.risk.position_sizing import calculate_position_size, calculate_reward_distance, calculate_risk_distance, calculate_rr_ratio
from arjiobot.risk.rr_profiles import calculate_fixed_risk_trade_math
from arjiobot.risk.risk_models import AccountSnapshot, OpenRiskState, RiskConfig, RiskRejectionReason
from arjiobot.strategy.strategy_models import SignalAction, TradeSignal

logger = logging.getLogger(__name__)


def calculate_max_safe_leverage(
    entry_price,
    sl_price,
    risk_per_trade,
    maintenance_margin_rate=0.004,
    close_fee_rate=0.0003,
    target_mmr=0.70,
) -> int:
    """Maximum leverage at which MMR stays below target_mmr the instant SL is hit.

    Sizing margin as notional/leverage alone can leave maintenance margin
    already at or past 100% (liquidation) by the time price reaches the stop
    - liquidation fires before the bot's own SL does. The fix is margin big
    enough to absorb the configured risk AND keep maintenance margin under
    target_mmr at the stop price:

        Q = risk_per_trade / abs(entry_price - sl_price)   # position size from risk
        N = Q * entry_price                                 # notional value
        k = maintenance_margin_rate + close_fee_rate
        MM_stop = Q * sl_price * k                          # maintenance margin at stop price
        M_required = risk_per_trade + (MM_stop / target_mmr)  # minimum margin needed
        L_max = N / M_required                              # maximum safe leverage

    Works for both long and short - sl_price is always the stop level,
    abs(entry_price - sl_price) makes the direction irrelevant.

    Returns int (floor), minimum 1. Never raises - any invalid input (zero/
    negative price, entry == sl_price, etc.) logs a warning and returns 1,
    the most conservative possible leverage, rather than propagating an
    exception into the execution path.
    """
    try:
        entry = to_decimal(entry_price)
        stop = to_decimal(sl_price)
        risk = to_decimal(risk_per_trade)
        k = to_decimal(maintenance_margin_rate) + to_decimal(close_fee_rate)
        target = to_decimal(target_mmr)
        sl_distance = abs(entry - stop)
        if entry <= 0 or stop <= 0 or risk <= 0 or target <= 0 or sl_distance <= 0:
            raise ValueError("entry_price, sl_price, risk_per_trade, target_mmr must be positive and entry_price must differ from sl_price")
        quantity = risk / sl_distance
        notional = quantity * entry
        mm_at_stop = quantity * stop * k
        margin_required = risk + (mm_at_stop / target)
        if margin_required <= 0:
            raise ValueError("margin_required must be positive")
        max_leverage = (notional / margin_required).to_integral_value(rounding=ROUND_FLOOR)
        return max(int(max_leverage), 1)
    except Exception:
        logger.warning(
            "calculate_max_safe_leverage failed for entry_price=%s sl_price=%s risk_per_trade=%s "
            "maintenance_margin_rate=%s close_fee_rate=%s target_mmr=%s - defaulting to 1x (most conservative)",
            entry_price,
            sl_price,
            risk_per_trade,
            maintenance_margin_rate,
            close_fee_rate,
            target_mmr,
            exc_info=True,
        )
        return 1


def validate_signal_risk(
    *,
    signal: TradeSignal,
    risk_config: RiskConfig,
    account_snapshot: AccountSnapshot,
    open_risk_state: OpenRiskState,
) -> tuple[tuple[RiskRejectionReason, ...], dict[str, Decimal]]:
    """Validate risk constraints and return rejection reasons plus metrics."""
    reasons: list[RiskRejectionReason] = []
    metrics: dict[str, Decimal] = {}
    is_bullish = signal.action is SignalAction.MARKET_BUY_READY
    if signal.action not in (SignalAction.MARKET_SELL_READY, SignalAction.MARKET_BUY_READY):
        reasons.append(RiskRejectionReason.UNSUPPORTED_SIGNAL_ACTION)
    if signal.entry_reference_price is None:
        reasons.append(RiskRejectionReason.MISSING_ENTRY_REFERENCE_PRICE)
        return tuple(reasons), metrics
    if risk_config.fixed_risk_amount is None or risk_config.fixed_risk_amount <= Decimal("0"):
        reasons.append(RiskRejectionReason.INVALID_FIXED_RISK_AMOUNT)
    if signal.stop_reference_price is None:
        reasons.append(RiskRejectionReason.INVALID_STOP_RELATIONSHIP)
    elif is_bullish and signal.stop_reference_price >= signal.entry_reference_price:
        reasons.append(RiskRejectionReason.INVALID_STOP_RELATIONSHIP)
    elif not is_bullish and signal.stop_reference_price <= signal.entry_reference_price:
        reasons.append(RiskRejectionReason.INVALID_STOP_RELATIONSHIP)
    if reasons:
        return tuple(reasons), metrics

    time_based_exit = risk_config.selected_rr_profile == "TIME_BASED_EXIT"
    if time_based_exit:
        risk_distance_for_size = abs(signal.stop_reference_price - signal.entry_reference_price)
        if risk_distance_for_size <= Decimal("0"):
            reasons.append(RiskRejectionReason.RISK_DISTANCE_ZERO_OR_NEGATIVE)
            return tuple(reasons), metrics
        rr_math = type(
            "TimeExitRiskMath",
            (),
            {
                "fixed_risk_amount": risk_config.fixed_risk_amount,
                "selected_rr_value": Decimal("0"),
                "target_reward_amount": Decimal("0"),
                "actual_risk_amount": risk_config.fixed_risk_amount,
                "expected_reward_amount": Decimal("0"),
                "actual_rr": Decimal("0"),
                "take_profit": None,
            },
        )()
    else:
        try:
            rr_math = calculate_fixed_risk_trade_math(
                direction=signal.direction,
                entry=signal.entry_reference_price,
                stop_loss=signal.stop_reference_price,
                fixed_risk_amount=risk_config.fixed_risk_amount,
                selected_rr_profile=risk_config.selected_rr_profile,
                final_target_price=signal.final_target_price,
            )
        except ValueError as exc:
            reason = RiskRejectionReason.INVALID_RR_PROFILE if "RR" in str(exc) else RiskRejectionReason.FIXED_RISK_VALIDATION_FAILED
            reasons.append(reason)
            metrics["risk_error"] = Decimal("0")
            return tuple(reasons), metrics

    risk_distance = calculate_risk_distance(entry_reference_price=signal.entry_reference_price, stop_reference_price=signal.stop_reference_price, direction=signal.direction)
    reward_distance = Decimal("0") if time_based_exit else calculate_reward_distance(entry_reference_price=signal.entry_reference_price, final_target_price=rr_math.take_profit, direction=signal.direction)
    rr_ratio = Decimal("0") if time_based_exit else calculate_rr_ratio(
        entry_reference_price=signal.entry_reference_price,
        stop_reference_price=signal.stop_reference_price,
        final_target_price=rr_math.take_profit,
    )
    metrics["risk_distance"] = risk_distance
    metrics["reward_distance"] = reward_distance
    metrics["rr_ratio"] = rr_ratio
    metrics["fixed_risk_amount"] = rr_math.fixed_risk_amount
    metrics["selected_rr_value"] = rr_math.selected_rr_value
    metrics["target_reward_amount"] = rr_math.target_reward_amount
    metrics["actual_risk_amount"] = rr_math.actual_risk_amount
    metrics["expected_reward_amount"] = rr_math.expected_reward_amount
    metrics["actual_rr"] = rr_math.actual_rr
    metrics["calculated_take_profit_price"] = rr_math.take_profit
    if risk_distance <= Decimal("0"):
        reasons.append(RiskRejectionReason.RISK_DISTANCE_ZERO_OR_NEGATIVE)
    if not time_based_exit and rr_ratio < risk_config.minimum_rr_ratio:
        reasons.append(RiskRejectionReason.RR_TOO_LOW)

    position = calculate_position_size(
        risk_amount=rr_math.fixed_risk_amount,
        entry_reference_price=signal.entry_reference_price,
        stop_reference_price=signal.stop_reference_price,
        direction=signal.direction,
    )
    try:
        isolated = calculate_required_margin(
            fixed_sl_loss=rr_math.fixed_risk_amount,
            entry_price=signal.entry_reference_price,
            stop_loss=signal.stop_reference_price,
            max_leverage=risk_config.max_leverage,
            available_margin=account_snapshot.available_margin,
            fee_rate=DEFAULT_FEE_RATE,
            slippage_rate=DEFAULT_SLIPPAGE_BUFFER_RATE,
        )
    except ValueError as exc:
        if "BLOCKED_INSUFFICIENT_AVAILABLE_MARGIN" in str(exc):
            reasons.append(RiskRejectionReason.INSUFFICIENT_AVAILABLE_MARGIN)
        else:
            reasons.append(RiskRejectionReason.FIXED_RISK_VALIDATION_FAILED)
        isolated = None
    # isolated.quantity/notional_position_size (when available) is the single
    # source of truth the min/max-size and exposure checks below validate
    # against, since it is also what actually gets traded - risk_engine.py
    # builds the trade plan from `isolated`, not from the separate `position`
    # calculation. calculate_position_size is kept only as a fallback for
    # when calculate_required_margin itself failed (e.g. insufficient
    # margin), so these checks still have a reasonable number to evaluate
    # even though the trade is already rejected via
    # INSUFFICIENT_AVAILABLE_MARGIN. Before this, the two were two
    # independent implementations of the same math that happened to agree
    # numerically but had no shared source of truth.
    applied_position_size = isolated.quantity if isolated is not None else position.position_size
    applied_notional_value = isolated.notional_position_size if isolated is not None else position.notional_value
    if isolated is not None:
        metrics["position_size"] = isolated.quantity
        metrics["notional_value"] = isolated.notional_position_size
        metrics["required_leverage"] = isolated.required_leverage
        metrics["approved_leverage"] = isolated.applied_leverage
        metrics["required_margin"] = isolated.margin_amount
        metrics["applied_margin_amount"] = isolated.margin_amount
        metrics["price_risk_percent"] = isolated.price_risk_percent
        metrics["max_allowed_leverage"] = isolated.max_allowed_leverage
        metrics["quantity"] = isolated.quantity
        metrics["expected_loss_at_sl"] = isolated.expected_loss_at_sl
    else:
        metrics["position_size"] = position.position_size
        metrics["notional_value"] = position.notional_value
        metrics["required_leverage"] = Decimal("0")
        metrics["approved_leverage"] = Decimal("0")
        metrics["required_margin"] = Decimal("0")
    if open_risk_state.open_trade_count >= risk_config.max_open_trades:
        reasons.append(RiskRejectionReason.MAX_OPEN_TRADES_REACHED)

    daily_remaining = daily_loss_capacity_remaining(
        max_daily_loss=risk_config.max_daily_loss,
        current_daily_pnl=open_risk_state.current_daily_pnl,
        reserved_risk_amount=open_risk_state.reserved_risk_amount,
    )
    weekly_remaining = weekly_loss_capacity_remaining(
        max_weekly_loss=risk_config.max_weekly_loss,
        current_weekly_pnl=open_risk_state.current_weekly_pnl,
        reserved_risk_amount=open_risk_state.reserved_risk_amount,
    )
    metrics["daily_loss_capacity_remaining"] = daily_remaining
    metrics["weekly_loss_capacity_remaining"] = weekly_remaining
    if risk_config.risk_amount_per_trade > daily_remaining:
        reasons.append(RiskRejectionReason.DAILY_LOSS_LIMIT_REACHED)
    if risk_config.risk_amount_per_trade > weekly_remaining:
        reasons.append(RiskRejectionReason.WEEKLY_LOSS_LIMIT_REACHED)
    if applied_position_size < risk_config.min_position_size:
        reasons.append(RiskRejectionReason.POSITION_SIZE_TOO_SMALL)
    if applied_position_size > risk_config.max_position_size:
        reasons.append(RiskRejectionReason.POSITION_SIZE_TOO_LARGE)
    if not risk_config.allow_multiple_positions_same_symbol and has_same_symbol_exposure(symbol=signal.symbol, open_symbol_exposure=open_risk_state.open_symbol_exposure):
        reasons.append(RiskRejectionReason.SAME_SYMBOL_EXPOSURE_BLOCKED)
    exposure_after = exposure_after_trade(symbol=signal.symbol, open_symbol_exposure=open_risk_state.open_symbol_exposure, notional_value=applied_notional_value)
    metrics["exposure_after_trade"] = exposure_after
    if exposure_after > risk_config.max_symbol_exposure:
        reasons.append(RiskRejectionReason.SYMBOL_EXPOSURE_LIMIT_REACHED)
    if account_snapshot.account_equity <= Decimal("0"):
        reasons.append(RiskRejectionReason.ACCOUNT_EQUITY_TOO_LOW)
    return tuple(reasons), metrics
