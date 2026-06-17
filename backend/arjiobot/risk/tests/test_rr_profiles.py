"""Selectable TP/RR fixed-risk tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from arjiobot.risk.rr_profiles import PRODUCTION_RR_PROFILE, PRODUCTION_RR_VALUE, calculate_fixed_risk_trade_math, calculate_pnl


def _math(direction: str, risk: str = "100"):
    return calculate_fixed_risk_trade_math(
        direction=direction,
        entry=Decimal("100"),
        stop_loss=Decimal("90") if direction == "BULLISH" else Decimal("110"),
        fixed_risk_amount=Decimal(risk),
        selected_rr_profile=PRODUCTION_RR_PROFILE,
    )


def test_production_default_rr_1_5_remains_available() -> None:
    assert PRODUCTION_RR_PROFILE == "RR_1_5"
    assert PRODUCTION_RR_VALUE == Decimal("1.5")


@pytest.mark.parametrize(
    ("direction", "expected_tp", "expected_pnl"),
    (
        ("BULLISH", Decimal("115.0"), Decimal("150.0")),
        ("BEARISH", Decimal("85.0"), Decimal("150.0")),
    ),
)
def test_fixed_risk_uses_selected_rr_1_5(direction: str, expected_tp: Decimal, expected_pnl: Decimal) -> None:
    result = _math(direction)

    assert result.selected_rr_profile == "RR_1_5"
    assert result.selected_rr_value == Decimal("1.5")
    assert result.take_profit == expected_tp
    assert result.position_size == Decimal("10")
    assert result.actual_risk_amount == Decimal("100")
    assert result.actual_rr == Decimal("1.5")
    assert result.expected_reward_amount == expected_pnl
    assert calculate_pnl(direction=direction, entry_price=Decimal("100"), exit_price=result.take_profit, position_size=result.position_size) == expected_pnl
    assert calculate_pnl(direction=direction, entry_price=Decimal("100"), exit_price=result.stop_loss, position_size=result.position_size) == Decimal("-100")


def test_supported_rr_1_0_can_be_selected() -> None:
    result = calculate_fixed_risk_trade_math(
        direction="BULLISH",
        entry=Decimal("100"),
        stop_loss=Decimal("90"),
        fixed_risk_amount=Decimal("100"),
        selected_rr_profile="RR_1_0",
    )

    assert result.selected_rr_profile == "RR_1_0"
    assert result.selected_rr_value == Decimal("1.0")
    assert result.take_profit == Decimal("110.0")
    assert result.expected_reward_amount == Decimal("100.0")


def test_leg_target_research_uses_signal_target() -> None:
    result = calculate_fixed_risk_trade_math(
        direction="BEARISH",
        entry=Decimal("100"),
        stop_loss=Decimal("110"),
        final_target_price=Decimal("82"),
        fixed_risk_amount=Decimal("100"),
        selected_rr_profile="LEG_TARGET_RESEARCH",
    )

    assert result.selected_rr_profile == "LEG_TARGET_RESEARCH"
    assert result.take_profit == Decimal("82")
    assert result.actual_rr == Decimal("1.8")
    assert result.expected_reward_amount == Decimal("180.0")


def test_unsupported_rr_profiles_are_rejected() -> None:
    for old_profile in ("RR_" + "1_1", "RR_" + "1_1_5", "RR_" + "2_0", "RR_" + "2_5", "RR_" + "3_0", "RR_" + "4_0"):
        with pytest.raises(ValueError, match="unknown TP/RR profile"):
            calculate_fixed_risk_trade_math(
                direction="BULLISH",
                entry=Decimal("100"),
                stop_loss=Decimal("90"),
                fixed_risk_amount=Decimal("100"),
                selected_rr_profile=old_profile,
            )


def test_invalid_fixed_risk_rejected() -> None:
    with pytest.raises(ValueError, match="fixed_risk_amount"):
        _math("BULLISH", risk="0")


def test_pnl_changes_when_fixed_risk_changes_but_rr_stays_1_5() -> None:
    risk_100 = _math("BULLISH", risk="100")
    risk_200 = _math("BULLISH", risk="200")

    assert risk_100.actual_rr == Decimal("1.5")
    assert risk_200.actual_rr == Decimal("1.5")
    assert risk_100.position_size == Decimal("10")
    assert risk_200.position_size == Decimal("20")
    assert calculate_pnl(direction="BULLISH", entry_price=risk_100.entry, exit_price=risk_100.take_profit, position_size=risk_100.position_size) == Decimal("150.0")
    assert calculate_pnl(direction="BULLISH", entry_price=risk_200.entry, exit_price=risk_200.take_profit, position_size=risk_200.position_size) == Decimal("300.0")
