"""Slippage tests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.backtesting.slippage import apply_bearish_entry_slippage, apply_bearish_exit_slippage, calculate_slippage_paid


def test_bearish_slippage_adjustments() -> None:
    assert apply_bearish_entry_slippage(Decimal("100"), Decimal("10")) == Decimal("99.900")
    assert apply_bearish_exit_slippage(Decimal("90"), Decimal("10")) == Decimal("90.090")
    assert calculate_slippage_paid(raw_entry=100, adjusted_entry=99, raw_exit=90, adjusted_exit=91, position_size=2) == Decimal("4")

