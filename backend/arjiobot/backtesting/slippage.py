"""Slippage model for deterministic backtests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal


def bps_multiplier(fixed_bps) -> Decimal:
    """Return decimal bps multiplier."""
    return to_decimal(fixed_bps) / Decimal("10000")


def apply_bearish_entry_slippage(price, fixed_bps) -> Decimal:
    """Market sell entry is worse at a lower price."""
    value = to_decimal(price)
    return value * (Decimal("1") - bps_multiplier(fixed_bps))


def apply_bearish_exit_slippage(price, fixed_bps) -> Decimal:
    """Bearish exit is worse at a higher buy-to-cover price."""
    value = to_decimal(price)
    return value * (Decimal("1") + bps_multiplier(fixed_bps))


def calculate_slippage_paid(*, raw_entry, adjusted_entry, raw_exit, adjusted_exit, position_size) -> Decimal:
    """Return absolute slippage cost."""
    size = abs(to_decimal(position_size))
    return (abs(to_decimal(raw_entry) - to_decimal(adjusted_entry)) * size) + (
        abs(to_decimal(raw_exit) - to_decimal(adjusted_exit)) * size
    )
