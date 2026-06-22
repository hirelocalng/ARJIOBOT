"""Strict isolated-margin order sizing guard."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping

from arjiobot.risk.isolated_margin import calculate_required_margin


class OrderSizingGuardError(ValueError):
    """Raised when an exchange order is missing locked risk sizing."""


def validate_isolated_order_payload(payload: Mapping[str, object]) -> dict[str, str]:
    """Validate selected risk fields and return normalized sizing metadata."""
    trade_type = str(payload.get("trade_type") or "").upper()
    margin_mode = str(payload.get("margin_mode") or "").lower()
    if trade_type != "ISOLATED_MARGIN" or margin_mode != "isolated":
        raise OrderSizingGuardError("margin mode must be isolated")

    selected_starting_balance = _positive_decimal(payload.get("selected_starting_balance"), "selected_starting_balance")
    selected_fixed_risk_amount = _positive_decimal(
        payload.get("selected_fixed_risk_amount") or payload.get("risk_amount"),
        "selected_fixed_risk_amount",
    )
    max_allowed_leverage = _positive_decimal(
        payload.get("max_allowed_leverage") or payload.get("selected_max_leverage"),
        "selected_max_leverage",
    )
    entry_price = _positive_decimal(payload.get("entry_price") or payload.get("entry_reference_price"), "entry_price")
    stop_loss = _positive_decimal(payload.get("stop_loss") or payload.get("stop_loss_price"), "stop_loss")
    try:
        # This guard predates fee/slippage-aware sizing and is not part of the
        # live trading path (see bitget_environment.py/live_automation.py for
        # that) - explicitly zeroed here to keep its existing, narrower
        # contract (locked quantity matches SL-distance-only sizing) rather
        # than silently inheriting calculate_required_margin's new defaults.
        sizing = calculate_required_margin(
            fixed_sl_loss=selected_fixed_risk_amount,
            entry_price=entry_price,
            stop_loss=stop_loss,
            max_leverage=max_allowed_leverage,
            available_margin=selected_starting_balance,
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
        )
    except ValueError as exc:
        raise OrderSizingGuardError(str(exc)) from exc

    applied_leverage = _positive_decimal(payload.get("applied_leverage") or payload.get("leverage"), "applied_leverage")
    quantity = _positive_decimal(payload.get("quantity") or payload.get("position_size"), "quantity")
    if abs(applied_leverage - sizing.applied_leverage) > Decimal("0.00000001"):
        raise OrderSizingGuardError("exchange does not confirm leverage was set correctly")
    if abs(quantity - sizing.quantity) > Decimal("0.00000001"):
        raise OrderSizingGuardError("quantity does not match selected fixed risk sizing")
    if str(payload.get("risk_lock_status", "PASSED")).upper() != "PASSED":
        raise OrderSizingGuardError("risk lock failed")
    if str(payload.get("environment_lock_status", "PASSED")).upper() != "PASSED":
        raise OrderSizingGuardError("environment lock failed")
    if str(payload.get("exchange_lock_status", "PASSED")).upper() != "PASSED":
        raise OrderSizingGuardError("exchange lock failed")
    if str(payload.get("profile_lock_status", "PASSED")).upper() != "PASSED":
        raise OrderSizingGuardError("profile lock failed")

    return {
        "selected_starting_balance": str(selected_starting_balance),
        "applied_starting_balance": str(selected_starting_balance),
        "selected_fixed_risk_amount": str(selected_fixed_risk_amount),
        "applied_margin_amount": str(sizing.margin_amount),
        "risk_amount": str(sizing.risk_amount),
        "trade_type": sizing.trade_type,
        "margin_mode": sizing.margin_mode,
        "entry_price": str(entry_price),
        "stop_loss": str(stop_loss),
        "price_risk_percent": str(sizing.price_risk_percent),
        "required_leverage": str(sizing.required_leverage),
        "applied_leverage": str(sizing.applied_leverage),
        "max_allowed_leverage": str(sizing.max_allowed_leverage),
        "notional_position_size": str(sizing.notional_position_size),
        "quantity": str(sizing.quantity),
        "expected_loss_at_sl": str(sizing.expected_loss_at_sl),
        "risk_lock_status": "PASSED",
        "environment_lock_status": "PASSED",
        "exchange_lock_status": "PASSED",
        "profile_lock_status": "PASSED",
    }


def _positive_decimal(value: object, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OrderSizingGuardError(f"{field_name} must be numeric") from exc
    if parsed <= 0:
        raise OrderSizingGuardError(f"{field_name} must be greater than zero")
    return parsed
