"""Fee model for deterministic backtests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal


def calculate_fees(*, entry_price, exit_price, position_size, fee_rate) -> Decimal:
    """Apply fees to entry and exit notional."""
    entry = to_decimal(entry_price)
    exit_ = to_decimal(exit_price)
    size = abs(to_decimal(position_size))
    rate = to_decimal(fee_rate)
    if rate < Decimal("0"):
        raise ValueError("fee_rate cannot be negative")
    return (entry * size * rate) + (exit_ * size * rate)
