"""Exposure-control logic."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal


def exposure_after_trade(*, symbol: str, open_symbol_exposure: dict[str, Decimal], notional_value) -> Decimal:
    """Return same-symbol exposure after a proposed trade."""
    return open_symbol_exposure.get(symbol.upper(), Decimal("0")) + to_decimal(notional_value)


def has_same_symbol_exposure(*, symbol: str, open_symbol_exposure: dict[str, Decimal]) -> bool:
    """Return whether symbol has existing exposure."""
    return open_symbol_exposure.get(symbol.upper(), Decimal("0")) > Decimal("0")
