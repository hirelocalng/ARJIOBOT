"""Fee tests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.backtesting.fees import calculate_fees


def test_fee_calculation_entry_and_exit() -> None:
    fees = calculate_fees(entry_price=Decimal("100"), exit_price=Decimal("90"), position_size=Decimal("2"), fee_rate=Decimal("0.001"))

    assert fees == Decimal("0.380")

