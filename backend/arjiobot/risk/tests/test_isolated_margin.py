"""Isolated-margin sizing tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from arjiobot.risk.isolated_margin import calculate_isolated_margin_plan, calculate_required_margin


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


def test_required_margin_skips_when_available_margin_is_insufficient() -> None:
    with pytest.raises(ValueError, match="BLOCKED_INSUFFICIENT_AVAILABLE_MARGIN"):
        calculate_required_margin(fixed_sl_loss=Decimal("10"), entry_price=Decimal("100"), stop_loss=Decimal("104"), max_leverage=Decimal("5"), available_margin=Decimal("40"))


def test_required_margin_trades_when_available_margin_exactly_covers_it() -> None:
    # fee_rate/slippage_rate=0 here to isolate the pure margin/leverage
    # relationship this test is about - see
    # test_fee_and_slippage_buffer_reduce_position_size_so_total_loss_matches_fixed_risk
    # below for the fee/slippage-aware path.
    plan = calculate_required_margin(
        fixed_sl_loss=Decimal("10"), entry_price=Decimal("100"), stop_loss=Decimal("104"), max_leverage=Decimal("5"), available_margin=Decimal("50"), fee_rate=Decimal("0"), slippage_rate=Decimal("0")
    )

    assert plan.can_execute is True
    assert plan.required_leverage == Decimal("5")
    assert plan.applied_leverage == Decimal("5")
    assert plan.margin_amount == Decimal("50")
    assert plan.risk_amount == Decimal("10")
    assert plan.expected_loss_at_sl == Decimal("10")


def test_required_margin_decreases_for_wider_stop_distance() -> None:
    plan = calculate_required_margin(
        fixed_sl_loss=Decimal("10"), entry_price=Decimal("100"), stop_loss=Decimal("110"), max_leverage=Decimal("10"), available_margin=Decimal("500"), fee_rate=Decimal("0"), slippage_rate=Decimal("0")
    )

    assert plan.can_execute is True
    assert plan.margin_amount == Decimal("10")


def test_required_margin_decouples_margin_from_risk_amount() -> None:
    plan = calculate_required_margin(
        fixed_sl_loss=Decimal("10"), entry_price=Decimal("100"), stop_loss=Decimal("104"), max_leverage=Decimal("10"), available_margin=Decimal("500"), fee_rate=Decimal("0"), slippage_rate=Decimal("0")
    )

    assert plan.can_execute is True
    assert plan.risk_amount == Decimal("10")
    assert plan.margin_amount != plan.risk_amount
    assert plan.margin_amount == Decimal("25")


def test_fee_and_slippage_buffer_reduce_position_size_so_total_loss_matches_fixed_risk() -> None:
    """The actual fix for the $2.35-loss-on-$2-risk bug: with realistic fee
    and slippage rates, the position is sized down up front so SL-distance
    loss + fees + slippage TOGETHER equal fixed_sl_loss, not the SL-distance
    loss alone with fees stacked uncounted on top."""
    plan = calculate_required_margin(
        fixed_sl_loss=Decimal("2"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("99"),
        max_leverage=Decimal("50"),
        available_margin=Decimal("1000"),
        fee_rate=Decimal("0.0012"),
        slippage_rate=Decimal("0.002"),
    )

    assert plan.expected_loss_at_sl < Decimal("2"), "SL-only loss must be less than the full budget once fees/slippage are reserved"
    assert plan.estimated_fee > Decimal("0")
    assert plan.estimated_slippage > Decimal("0")
    assert abs(plan.total_worst_case_loss - Decimal("2")) < Decimal("0.0001"), "total realized loss must still target the configured fixed_risk_amount"


def test_zero_fee_and_slippage_reproduces_old_sl_only_behavior() -> None:
    """Explicit fee_rate=0/slippage_rate=0 must behave identically to the
    pre-fix formula - this is what every other test in this file relies on."""
    plan = calculate_required_margin(
        fixed_sl_loss=Decimal("10"), entry_price=Decimal("100"), stop_loss=Decimal("101"), max_leverage=Decimal("100"), available_margin=Decimal("1000"), fee_rate=Decimal("0"), slippage_rate=Decimal("0")
    )

    assert plan.expected_loss_at_sl == Decimal("10")
    assert plan.estimated_fee == Decimal("0")
    assert plan.estimated_slippage == Decimal("0")
    assert plan.total_worst_case_loss == Decimal("10")
