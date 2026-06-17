"""Leverage tests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.risk.leverage import calculate_leverage_plan


def test_leverage_calculation_and_clamp() -> None:
    low = calculate_leverage_plan(notional_value=Decimal("500"), available_margin=Decimal("1000"), max_leverage=Decimal("10"))
    high = calculate_leverage_plan(notional_value=Decimal("25000"), available_margin=Decimal("1000"), max_leverage=Decimal("10"))

    assert low.approved_leverage == Decimal("1")
    assert high.required_leverage == Decimal("25")
    assert high.approved_leverage == Decimal("10")

