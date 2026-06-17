"""Isolated-margin sizing tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from arjiobot.risk.isolated_margin import calculate_isolated_margin_plan


@pytest.mark.parametrize("margin", ("10", "25", "100"))
def test_isolated_margin_loss_at_sl_matches_selected_risk(margin: str) -> None:
    plan = calculate_isolated_margin_plan(entry_price=Decimal("100"), stop_loss=Decimal("101"), margin_amount=Decimal(margin), max_leverage=Decimal("100"))

    assert plan.trade_type == "ISOLATED_MARGIN"
    assert plan.margin_mode == "isolated"
    assert plan.margin_amount == Decimal(margin)
    assert plan.risk_amount == Decimal(margin)
    assert plan.required_leverage == Decimal("100")
    assert plan.expected_loss_at_sl == Decimal(margin)


@pytest.mark.parametrize(
    ("starting_balance", "margin"),
    (("100", "10"), ("500", "10"), ("1000", "25"), ("10000", "100")),
)
def test_selected_balance_and_risk_cases_use_fixed_risk_as_isolated_margin(starting_balance: str, margin: str) -> None:
    plan = calculate_isolated_margin_plan(entry_price=Decimal("100"), stop_loss=Decimal("101"), margin_amount=Decimal(margin), max_leverage=Decimal("100"))

    assert Decimal(starting_balance) > Decimal("0")
    assert plan.margin_amount == Decimal(margin)
    assert plan.risk_amount == Decimal(margin)
    assert plan.expected_loss_at_sl == Decimal(margin)


def test_required_leverage_above_max_is_blocked() -> None:
    with pytest.raises(ValueError, match="BLOCKED_REQUIRED_LEVERAGE_EXCEEDS_MAX"):
        calculate_isolated_margin_plan(entry_price=Decimal("100"), stop_loss=Decimal("101"), margin_amount=Decimal("10"), max_leverage=Decimal("50"))
