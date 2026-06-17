"""Position sizing tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from arjiobot.risk.position_sizing import calculate_position_size, calculate_reward_distance, calculate_risk_distance, calculate_rr_ratio


def test_position_sizing_and_distances() -> None:
    assert calculate_risk_distance(entry_reference_price=90, stop_reference_price=120) == Decimal("30")
    assert calculate_reward_distance(entry_reference_price=90, final_target_price=70) == Decimal("20")
    position = calculate_position_size(risk_amount=100, entry_reference_price=90, stop_reference_price=120)
    assert position.position_size == Decimal("3.333333333333333333333333333")
    assert calculate_rr_ratio(entry_reference_price=90, stop_reference_price=120, final_target_price=70) == Decimal("0.6666666666666666666666666667")


def test_zero_negative_risk_distance_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        calculate_position_size(risk_amount=100, entry_reference_price=120, stop_reference_price=90)

