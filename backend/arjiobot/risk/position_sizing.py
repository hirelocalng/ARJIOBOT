"""Position sizing logic."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal
from arjiobot.risk.risk_models import PositionSize


def calculate_risk_distance(*, entry_reference_price, stop_reference_price) -> Decimal:
    """Calculate bearish risk distance."""
    return to_decimal(stop_reference_price) - to_decimal(entry_reference_price)


def calculate_reward_distance(*, entry_reference_price, final_target_price) -> Decimal:
    """Calculate bearish reward distance."""
    return to_decimal(entry_reference_price) - to_decimal(final_target_price)


def calculate_position_size(*, risk_amount, entry_reference_price, stop_reference_price) -> PositionSize:
    """Calculate position size from risk amount and stop distance."""
    risk_amount_decimal = to_decimal(risk_amount)
    risk_distance = calculate_risk_distance(entry_reference_price=entry_reference_price, stop_reference_price=stop_reference_price)
    if risk_distance <= Decimal("0"):
        raise ValueError("risk_distance must be positive")
    position_size = risk_amount_decimal / risk_distance
    notional_value = position_size * to_decimal(entry_reference_price)
    return PositionSize(
        risk_amount=risk_amount_decimal,
        risk_distance=risk_distance,
        position_size=position_size,
        notional_value=notional_value,
    )


def calculate_rr_ratio(*, entry_reference_price, stop_reference_price, final_target_price) -> Decimal:
    """Calculate bearish reward/risk ratio."""
    risk_distance = abs(to_decimal(stop_reference_price) - to_decimal(entry_reference_price))
    reward_distance = abs(to_decimal(entry_reference_price) - to_decimal(final_target_price))
    if risk_distance <= Decimal("0"):
        return Decimal("0")
    return reward_distance / risk_distance
