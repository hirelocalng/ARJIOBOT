"""Isolated-margin sizing and order guard helpers.

calculate_required_margin (current, used by all live/paper isolated-margin
trades) decouples margin from the fixed SL-loss amount: position size is
derived purely from the fixed risk and stop distance, then the margin
required to open that position at the pair's max leverage is calculated
separately and checked against available margin. This avoids forcing
impossible leverage on low-leverage pairs just to keep margin == risk.

calculate_isolated_margin_plan / IsolatedMarginPlan are kept unchanged as a
legacy shim: scripts/backtest_csv.py still imports and constructs these
directly for its own profile-conditional backtest sizing path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal

logger = logging.getLogger(__name__)

ISOLATED_MARGIN_MODE = "isolated"
ISOLATED_TRADE_TYPE = "ISOLATED_MARGIN"
LOSS_TOLERANCE = Decimal("0.00000001")


def _without_exponent(value: Decimal) -> Decimal:
    """Avoid Decimal division producing scientific notation (e.g. 1E+1 instead of 10)."""
    if value.as_tuple().exponent > 0:
        return value.quantize(Decimal(1))
    return value


@dataclass(frozen=True, slots=True)
class IsolatedMarginPlan:
    margin_amount: Decimal
    risk_amount: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    price_risk_percent: Decimal
    required_leverage: Decimal
    applied_leverage: Decimal
    max_allowed_leverage: Decimal
    notional_position_size: Decimal
    quantity: Decimal
    expected_loss_at_sl: Decimal
    margin_mode: str = ISOLATED_MARGIN_MODE
    trade_type: str = ISOLATED_TRADE_TYPE

    def to_record(self) -> dict[str, str]:
        return {
            "trade_type": self.trade_type,
            "margin_mode": self.margin_mode,
            "applied_margin_amount": str(self.margin_amount),
            "risk_amount": str(self.risk_amount),
            "price_risk_percent": str(self.price_risk_percent),
            "required_leverage": str(self.required_leverage),
            "applied_leverage": str(self.applied_leverage),
            "max_allowed_leverage": str(self.max_allowed_leverage),
            "notional_position_size": str(self.notional_position_size),
            "quantity": str(self.quantity),
            "expected_loss_at_sl": str(self.expected_loss_at_sl),
        }


def calculate_isolated_margin_plan(*, entry_price, stop_loss, margin_amount, max_leverage) -> IsolatedMarginPlan:
    """Legacy sizing: forces margin == risk. Kept only for scripts/backtest_csv.py."""
    entry = to_decimal(entry_price)
    stop = to_decimal(stop_loss)
    margin = to_decimal(margin_amount)
    max_lev = to_decimal(max_leverage)
    if entry <= Decimal("0"):
        raise ValueError("entry_price must be greater than zero")
    if stop <= Decimal("0"):
        raise ValueError("stop_loss must be greater than zero")
    if margin <= Decimal("0"):
        raise ValueError("fixed_risk_amount must be greater than zero")
    if max_lev < Decimal("1"):
        raise ValueError("max_leverage must be at least 1")
    price_risk_percent = abs(entry - stop) / entry
    if price_risk_percent <= Decimal("0"):
        raise ValueError("price_risk_percent must be greater than zero")
    required_leverage = Decimal("1") / price_risk_percent
    if required_leverage > max_lev:
        raise ValueError("BLOCKED_REQUIRED_LEVERAGE_EXCEEDS_MAX")
    notional = margin * required_leverage
    quantity = notional / entry
    expected_loss = abs(entry - stop) * quantity
    if abs(expected_loss - margin) > max(LOSS_TOLERANCE, margin * Decimal("0.000001")):
        raise ValueError("expected_loss_at_sl does not match selected fixed risk amount")
    return IsolatedMarginPlan(
        margin_amount=margin,
        risk_amount=margin,
        entry_price=entry,
        stop_loss=stop,
        price_risk_percent=price_risk_percent,
        required_leverage=required_leverage,
        applied_leverage=required_leverage,
        max_allowed_leverage=max_lev,
        notional_position_size=notional,
        quantity=quantity,
        expected_loss_at_sl=expected_loss,
    )


@dataclass(frozen=True, slots=True)
class RequiredMarginPlan:
    margin_amount: Decimal
    risk_amount: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    price_risk_percent: Decimal
    required_leverage: Decimal
    applied_leverage: Decimal
    max_allowed_leverage: Decimal
    available_margin: Decimal
    can_execute: bool
    notional_position_size: Decimal
    quantity: Decimal
    expected_loss_at_sl: Decimal
    margin_mode: str = ISOLATED_MARGIN_MODE
    trade_type: str = ISOLATED_TRADE_TYPE

    def to_record(self) -> dict[str, str]:
        return {
            "trade_type": self.trade_type,
            "margin_mode": self.margin_mode,
            "applied_margin_amount": str(self.margin_amount),
            "risk_amount": str(self.risk_amount),
            "price_risk_percent": str(self.price_risk_percent),
            "required_leverage": str(self.required_leverage),
            "applied_leverage": str(self.applied_leverage),
            "max_allowed_leverage": str(self.max_allowed_leverage),
            "available_margin": str(self.available_margin),
            "can_execute": "YES" if self.can_execute else "NO",
            "notional_position_size": str(self.notional_position_size),
            "quantity": str(self.quantity),
            "expected_loss_at_sl": str(self.expected_loss_at_sl),
        }


def calculate_required_margin(*, fixed_sl_loss, entry_price, stop_loss, max_leverage, available_margin) -> RequiredMarginPlan:
    """Size an isolated-margin position so SL loss equals fixed_sl_loss, then
    derive the margin required to open it at the pair's max leverage.

    Position size (and therefore the dollar loss at SL) is fixed and
    independent of leverage/margin. Margin is calculated dynamically as
    required_notional / max_leverage and compared against available_margin;
    it is no longer forced to equal the risk amount.
    """
    entry = to_decimal(entry_price)
    stop = to_decimal(stop_loss)
    fixed_loss = to_decimal(fixed_sl_loss)
    max_lev = to_decimal(max_leverage)
    available = to_decimal(available_margin)
    if entry <= Decimal("0"):
        raise ValueError("entry_price must be greater than zero")
    if stop <= Decimal("0"):
        raise ValueError("stop_loss must be greater than zero")
    if fixed_loss <= Decimal("0"):
        raise ValueError("fixed_sl_loss must be greater than zero")
    if max_lev < Decimal("1"):
        raise ValueError("max_leverage must be at least 1")
    stop_distance_percent = abs(entry - stop) / entry
    if stop_distance_percent <= Decimal("0"):
        raise ValueError("stop_distance_percent must be greater than zero")

    required_notional = _without_exponent(fixed_loss / stop_distance_percent)
    quantity = _without_exponent(required_notional / entry)
    expected_loss = _without_exponent(abs(entry - stop) * quantity)
    if abs(expected_loss - fixed_loss) > max(LOSS_TOLERANCE, fixed_loss * Decimal("0.000001")):
        raise ValueError("expected_loss_at_sl does not match fixed_sl_loss")

    required_margin = _without_exponent(required_notional / max_lev)
    can_execute = required_margin <= available

    # extra={} fields are NOT rendered by dev_server.py's logging.basicConfig
    # format string (it only references %(asctime)s/%(levelname)s/%(name)s/
    # %(message)s) - every one of these numbers was silently dropped from the
    # actual log output, leaving just the bare line "Isolated margin sizing"
    # with no indication of why a trade was or wasn't sized. Put the values
    # directly in the message so they show up in Railway's log stream.
    logger.info(
        "Margin check: fixed_sl_loss=%s entry_price=%s stop_loss=%s stop_distance_percent=%s "
        "required_notional=%s max_leverage=%s required_margin=%s available_margin=%s sufficient=%s",
        fixed_loss,
        entry,
        stop,
        stop_distance_percent,
        required_notional,
        max_lev,
        required_margin,
        available,
        can_execute,
    )
    if not can_execute:
        logger.warning(
            "Margin check FAILED: required_margin=%s exceeds available_margin=%s - trade blocked before reaching Bitget",
            required_margin,
            available,
        )
        raise ValueError("BLOCKED_INSUFFICIENT_AVAILABLE_MARGIN")

    return RequiredMarginPlan(
        margin_amount=required_margin,
        risk_amount=fixed_loss,
        entry_price=entry,
        stop_loss=stop,
        price_risk_percent=stop_distance_percent,
        required_leverage=max_lev,
        applied_leverage=max_lev,
        max_allowed_leverage=max_lev,
        available_margin=available,
        can_execute=can_execute,
        notional_position_size=required_notional,
        quantity=quantity,
        expected_loss_at_sl=expected_loss,
    )
