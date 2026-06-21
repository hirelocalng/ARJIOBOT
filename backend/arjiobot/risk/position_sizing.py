"""Position sizing logic."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal
from arjiobot.risk.risk_models import PositionSize
from arjiobot.setup_tracker.setup_models import SetupDirection


def _is_bullish(direction: SetupDirection | str) -> bool:
    normalized = direction.value if isinstance(direction, SetupDirection) else str(direction).upper()
    return normalized == SetupDirection.BULLISH.value


def calculate_risk_distance(*, entry_reference_price, stop_reference_price, direction: SetupDirection | str = SetupDirection.BEARISH) -> Decimal:
    """Calculate risk distance (positive when the stop sits on the correct side of entry for ``direction``)."""
    entry_decimal = to_decimal(entry_reference_price)
    stop_decimal = to_decimal(stop_reference_price)
    if _is_bullish(direction):
        return entry_decimal - stop_decimal
    return stop_decimal - entry_decimal


def calculate_reward_distance(*, entry_reference_price, final_target_price, direction: SetupDirection | str = SetupDirection.BEARISH) -> Decimal:
    """Calculate reward distance (positive when the target sits on the correct side of entry for ``direction``)."""
    entry_decimal = to_decimal(entry_reference_price)
    target_decimal = to_decimal(final_target_price)
    if _is_bullish(direction):
        return target_decimal - entry_decimal
    return entry_decimal - target_decimal


def calculate_position_size(*, risk_amount, entry_reference_price, stop_reference_price, direction: SetupDirection | str = SetupDirection.BEARISH) -> PositionSize:
    """Calculate position size from risk amount and stop distance."""
    risk_amount_decimal = to_decimal(risk_amount)
    risk_distance = calculate_risk_distance(entry_reference_price=entry_reference_price, stop_reference_price=stop_reference_price, direction=direction)
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
