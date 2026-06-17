"""Loss-limit validation logic."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal


def daily_loss_capacity_remaining(*, max_daily_loss, current_daily_pnl, reserved_risk_amount) -> Decimal:
    """Return remaining daily risk capacity."""
    loss_used = abs(min(to_decimal(current_daily_pnl), Decimal("0")))
    return to_decimal(max_daily_loss) - loss_used - to_decimal(reserved_risk_amount)


def weekly_loss_capacity_remaining(*, max_weekly_loss, current_weekly_pnl, reserved_risk_amount) -> Decimal:
    """Return remaining weekly risk capacity."""
    loss_used = abs(min(to_decimal(current_weekly_pnl), Decimal("0")))
    return to_decimal(max_weekly_loss) - loss_used - to_decimal(reserved_risk_amount)
