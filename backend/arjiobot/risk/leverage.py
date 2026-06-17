"""Leverage calculation logic."""

from __future__ import annotations

from decimal import Decimal, ROUND_UP

from arjiobot.market_data.candle_models import to_decimal
from arjiobot.risk.risk_models import LeveragePlan


def calculate_leverage_plan(*, notional_value, available_margin, max_leverage) -> LeveragePlan:
    """Calculate conservative leverage plan."""
    notional = to_decimal(notional_value)
    margin = to_decimal(available_margin)
    max_lev = to_decimal(max_leverage)
    if margin <= Decimal("0"):
        raise ValueError("available_margin must be positive")
    required = notional / margin
    approved = Decimal("1") if required <= Decimal("1") else required.quantize(Decimal("0.01"), rounding=ROUND_UP)
    if approved > max_lev:
        approved = max_lev
    required_margin = notional / approved
    return LeveragePlan(required_leverage=required, approved_leverage=approved, required_margin=required_margin)
