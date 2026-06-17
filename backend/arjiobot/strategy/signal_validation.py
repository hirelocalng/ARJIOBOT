"""Final setup-to-signal validation rules."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from arjiobot.market_data.candle_models import ensure_utc
from arjiobot.setup_tracker.setup_models import Setup, SetupDirection, SetupState, SetupStatus
from arjiobot.strategy.strategy_models import SignalRejectionReason, SignalValidationResult


REQUIRED_SETUP_FIELDS = (
    "htf_fvg_id",
    "swing_16m_id",
    "expansion_16m_id",
    "fvg_16m_id",
    "fvg_12m_id",
    "fvg_8m_id",
    "one_minute_swing_id",
    "entry_fvg_id",
    "stop_reference_price",
    "final_target_price",
)

DIRECT_RETRACE_OPTIONAL_FIELDS = {"one_minute_swing_id"}


def latest_price_from_setup(setup: Setup) -> Decimal | None:
    """Return latest relevant price from setup metadata if available."""
    value = setup.metadata.get("latest_price")
    return Decimal(value) if value is not None else None


def entry_reference_price_from_setup(setup: Setup) -> Decimal | None:
    """Return v1 entry reference price, if known."""
    if "latest_price" in setup.metadata:
        return Decimal(setup.metadata["latest_price"])
    if "entry_fvg_tap_price" in setup.metadata:
        return Decimal(setup.metadata["entry_fvg_tap_price"])
    return None


def validate_setup_for_signal(
    setup: Setup,
    *,
    checked_at: datetime,
    duplicate_exists: bool = False,
) -> SignalValidationResult:
    """Validate whether a setup can become a trade signal."""
    errors: list[str] = []
    reason: SignalRejectionReason | None = None
    if not setup.setup_id:
        errors.append("setup_id is required")
        reason = SignalRejectionReason.MISSING_REQUIRED_FIELD
    if not setup.symbol:
        errors.append("symbol is required")
        reason = SignalRejectionReason.MISSING_REQUIRED_FIELD
    if setup.direction is not SetupDirection.BEARISH:
        errors.append("only bearish signals are supported in v1")
        reason = SignalRejectionReason.UNSUPPORTED_DIRECTION
    if setup.current_state is not SetupState.ENTRY_READY or setup.status is not SetupStatus.ENTRY_READY:
        errors.append("setup is not ENTRY_READY")
        reason = SignalRejectionReason.SETUP_NOT_ENTRY_READY
    if setup.current_state is SetupState.INVALIDATED or setup.status is SetupStatus.INVALIDATED:
        errors.append("setup is invalidated")
        reason = SignalRejectionReason.SETUP_INVALIDATED
    if setup.current_state is SetupState.EXPIRED or setup.status is SetupStatus.EXPIRED:
        errors.append("setup is expired")
        reason = SignalRejectionReason.SETUP_EXPIRED
    optional_fields: set[str] = set()
    if setup.metadata.get("entry_model") == "DIRECT_12M_RETRACE":
        optional_fields.update(DIRECT_RETRACE_OPTIONAL_FIELDS)
    missing = [field_name for field_name in REQUIRED_SETUP_FIELDS if field_name not in optional_fields and not getattr(setup, field_name)]
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
        reason = SignalRejectionReason.MISSING_REQUIRED_FIELD
    if duplicate_exists:
        errors.append("signal already generated for setup")
        reason = SignalRejectionReason.DUPLICATE_SIGNAL

    if setup.stop_reference_price is not None and setup.final_target_price is not None:
        if setup.stop_reference_price <= setup.final_target_price:
            errors.append("stop reference must be above final target for bearish setup")
            reason = SignalRejectionReason.INVALID_STOP_TARGET_RELATIONSHIP
        entry = entry_reference_price_from_setup(setup)
        if entry is not None and not (setup.stop_reference_price > entry > setup.final_target_price):
            errors.append("entry reference must sit between stop and target for bearish setup")
            reason = SignalRejectionReason.INVALID_STOP_TARGET_RELATIONSHIP
        latest = latest_price_from_setup(setup)
        if latest is not None and latest <= setup.final_target_price:
            errors.append("target already reached before signal")
            reason = SignalRejectionReason.TARGET_ALREADY_REACHED

    return SignalValidationResult(
        validation_passed=not errors,
        validation_errors=tuple(errors),
        rejection_reason=reason,
        checked_at=ensure_utc(checked_at),
    )
