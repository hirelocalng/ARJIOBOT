"""Fixed-risk TP/RR reward calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from arjiobot.market_data.candle_models import to_decimal
from arjiobot.setup_tracker.setup_models import SetupDirection


PRODUCTION_RR_PROFILE = "RR_1_5"
PRODUCTION_RR_VALUE = Decimal("1.5")
SUPPORTED_TP_MODELS = ("RR_1_0", "RR_1_0_RESEARCH", "RR_1_5", "LEG_TARGET_RESEARCH")
TOLERANCE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class FixedRiskTradeProfile:
    fixed_risk_amount: Decimal
    selected_rr_profile: str
    selected_rr_value: Decimal
    target_reward_amount: Decimal


@dataclass(frozen=True, slots=True)
class FixedRiskTradeMath:
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    fixed_risk_amount: Decimal
    selected_rr_profile: str
    selected_rr_value: Decimal
    target_reward_amount: Decimal
    position_size: Decimal
    actual_risk_amount: Decimal
    expected_reward_amount: Decimal
    actual_rr: Decimal


def resolve_rr_value(selected_rr_profile: str | None = PRODUCTION_RR_PROFILE) -> Decimal:
    """Resolve fixed-RR values. LEG_TARGET_RESEARCH is variable and resolves during trade math."""
    profile = (selected_rr_profile or "").strip().upper()
    if profile in ("", PRODUCTION_RR_PROFILE):
        return PRODUCTION_RR_VALUE
    if profile in {"RR_1_0", "RR_1_0_RESEARCH"}:
        return Decimal("1.0")
    if profile == "LEG_TARGET_RESEARCH":
        return Decimal("0")
    raise ValueError(f"unknown TP/RR profile: {selected_rr_profile}")


def resolve_fixed_risk_profile(
    *,
    fixed_risk_amount: Decimal | str | float | int,
    selected_rr_profile: str | None,
) -> FixedRiskTradeProfile:
    """Validate fixed risk and selected RR."""
    risk = to_decimal(fixed_risk_amount)
    if risk <= Decimal("0"):
        raise ValueError("fixed_risk_amount must be greater than 0")
    profile = (selected_rr_profile or PRODUCTION_RR_PROFILE).strip().upper()
    resolve_rr_value(profile)
    rr_value = resolve_rr_value(profile)
    return FixedRiskTradeProfile(
        fixed_risk_amount=risk,
        selected_rr_profile=profile,
        selected_rr_value=rr_value,
        target_reward_amount=risk * rr_value,
    )


def calculate_take_profit(*, direction: SetupDirection | str, entry, stop_loss, selected_rr_value) -> Decimal:
    """Calculate TP from entry, SL, and selected RR."""
    entry_decimal = to_decimal(entry)
    stop_decimal = to_decimal(stop_loss)
    rr = to_decimal(selected_rr_value)
    normalized = direction.value if isinstance(direction, SetupDirection) else str(direction).upper()
    if normalized == SetupDirection.BULLISH.value:
        risk_distance = entry_decimal - stop_decimal
        if risk_distance <= Decimal("0"):
            raise ValueError("bullish SL must be below entry")
        return entry_decimal + (risk_distance * rr)
    if normalized == SetupDirection.BEARISH.value:
        risk_distance = stop_decimal - entry_decimal
        if risk_distance <= Decimal("0"):
            raise ValueError("bearish SL must be above entry")
        return entry_decimal - (risk_distance * rr)
    raise ValueError(f"unsupported trade direction: {direction}")


def calculate_fixed_risk_trade_math(
    *,
    direction: SetupDirection | str,
    entry,
    stop_loss,
    fixed_risk_amount,
    selected_rr_profile: str | None,
    final_target_price=None,
) -> FixedRiskTradeMath:
    """Calculate TP, position size, fixed risk, and expected reward."""
    profile = resolve_fixed_risk_profile(
        fixed_risk_amount=fixed_risk_amount,
        selected_rr_profile=selected_rr_profile,
    )
    entry_decimal = to_decimal(entry)
    stop_decimal = to_decimal(stop_loss)
    risk_distance = abs(entry_decimal - stop_decimal)
    if risk_distance <= Decimal("0"):
        raise ValueError("stop_loss_distance must be greater than 0")
    if profile.selected_rr_profile == "LEG_TARGET_RESEARCH":
        if final_target_price is None:
            raise ValueError("LEG_TARGET_RESEARCH requires final_target_price")
        take_profit = to_decimal(final_target_price)
        normalized = direction.value if isinstance(direction, SetupDirection) else str(direction).upper()
        if normalized == SetupDirection.BEARISH.value and take_profit >= entry_decimal:
            raise ValueError("bearish LEG_TARGET_RESEARCH TP must be below entry")
        if normalized == SetupDirection.BULLISH.value and take_profit <= entry_decimal:
            raise ValueError("bullish LEG_TARGET_RESEARCH TP must be above entry")
        actual_rr = abs(take_profit - entry_decimal) / risk_distance
        selected_rr_value = actual_rr
        target_reward_amount = profile.fixed_risk_amount * actual_rr
    else:
        take_profit = calculate_take_profit(
            direction=direction,
            entry=entry_decimal,
            stop_loss=stop_decimal,
            selected_rr_value=profile.selected_rr_value,
        )
        actual_rr = abs(take_profit - entry_decimal) / risk_distance
        selected_rr_value = profile.selected_rr_value
        target_reward_amount = profile.target_reward_amount
    position_size = profile.fixed_risk_amount / risk_distance
    actual_risk_amount = risk_distance * position_size
    expected_reward_amount = profile.fixed_risk_amount * selected_rr_value
    if abs(actual_risk_amount - profile.fixed_risk_amount) > TOLERANCE:
        raise ValueError("actual_risk_amount does not match fixed_risk_amount")
    if profile.selected_rr_profile != "LEG_TARGET_RESEARCH" and abs(actual_rr - selected_rr_value) > TOLERANCE:
        raise ValueError("actual_rr does not match selected TP/RR profile")
    return FixedRiskTradeMath(
        entry=entry_decimal,
        stop_loss=stop_decimal,
        take_profit=take_profit,
        fixed_risk_amount=profile.fixed_risk_amount,
        selected_rr_profile=profile.selected_rr_profile,
        selected_rr_value=selected_rr_value,
        target_reward_amount=target_reward_amount,
        position_size=position_size,
        actual_risk_amount=actual_risk_amount,
        expected_reward_amount=expected_reward_amount,
        actual_rr=actual_rr,
    )


def calculate_pnl(*, direction: SetupDirection | str, entry_price, exit_price, position_size) -> Decimal:
    """Calculate PnL from direction, price movement, and size."""
    entry = to_decimal(entry_price)
    exit_decimal = to_decimal(exit_price)
    size = to_decimal(position_size)
    normalized = direction.value if isinstance(direction, SetupDirection) else str(direction).upper()
    if normalized == SetupDirection.BULLISH.value:
        return (exit_decimal - entry) * size
    if normalized == SetupDirection.BEARISH.value:
        return (entry - exit_decimal) * size
    raise ValueError(f"unsupported trade direction: {direction}")
