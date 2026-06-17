"""Isolated-margin sizing and order guard helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal

ISOLATED_MARGIN_MODE = "isolated"
ISOLATED_TRADE_TYPE = "ISOLATED_MARGIN"
LOSS_TOLERANCE = Decimal("0.00000001")


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
    """Size an isolated-margin position so SL loss equals selected margin/risk."""
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
