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


def test_fixed_sl_loss_is_the_dollar_loss_at_stop_not_a_budget_shared_with_fees() -> None:
    """fixed_sl_loss is the dollar loss AT THE STOP LOSS, never the margin to
    post and never a budget shared with fees/slippage - those are completely
    different things. expected_loss_at_sl must exactly equal fixed_sl_loss
    regardless of fee_rate/slippage_rate; fees/slippage are a real,
    additional cost layered on top (total_worst_case_loss), not carved out
    of the configured risk amount (which is what previously made a $2 risk
    setting produce only a ~$1.69 real loss at stop loss)."""
    plan = calculate_required_margin(
        fixed_sl_loss=Decimal("2"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("99"),
        max_leverage=Decimal("50"),
        available_margin=Decimal("1000"),
        fee_rate=Decimal("0.0012"),
        slippage_rate=Decimal("0.002"),
    )

    assert plan.expected_loss_at_sl == Decimal("2"), "the SL-distance dollar loss must exactly equal the configured fixed_sl_loss"
    assert plan.estimated_fee > Decimal("0")
    assert plan.estimated_slippage > Decimal("0")
    assert plan.total_worst_case_loss > Decimal("2"), "fees/slippage are additional on top of the exact SL-distance loss, not absorbed into it"


def test_worked_example_2_dollar_risk_at_75x_leverage_produces_500_apt() -> None:
    """The exact worked example from the bug report: $2 risk, entry 0.6640,
    stop 0.6680 (short), 75x leverage -> ~500 APT, ~$332 notional, ~$4.43
    margin, and critically an exact $2.00 loss at stop loss."""
    plan = calculate_required_margin(
        fixed_sl_loss=Decimal("2.00"),
        entry_price=Decimal("0.6640"),
        stop_loss=Decimal("0.6680"),
        max_leverage=Decimal("75"),
        available_margin=Decimal("1000"),
        fee_rate=Decimal("0.0006"),
        slippage_rate=Decimal("0.0005"),
    )

    assert plan.quantity == Decimal("500")
    assert plan.notional_position_size == Decimal("332.0000")
    assert abs(plan.margin_amount - Decimal("4.43")) < Decimal("0.01")
    assert plan.expected_loss_at_sl == Decimal("2.0000"), "a $2 risk setting must produce exactly a $2 loss at stop loss"


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
