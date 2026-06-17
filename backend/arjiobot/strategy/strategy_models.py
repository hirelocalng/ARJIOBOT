"""Data models for the ArjioBot Strategy Engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import ensure_utc, to_decimal
from arjiobot.setup_tracker.setup_models import SetupDirection, SetupState


class SignalAction(str, Enum):
    """Supported signal actions."""

    MARKET_SELL_READY = "MARKET_SELL_READY"
    MARKET_BUY_READY = "MARKET_BUY_READY"


class EntryReferenceType(str, Enum):
    """Supported entry reference types."""

    MARKET_SELL = "MARKET_SELL"
    MARKET_BUY = "MARKET_BUY"


class SignalStatus(str, Enum):
    """Signal lifecycle states."""

    GENERATED = "GENERATED"
    REJECTED = "REJECTED"
    SENT_TO_RISK_ENGINE = "SENT_TO_RISK_ENGINE"
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    SENT_TO_EXECUTION = "SENT_TO_EXECUTION"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SignalRejectionReason(str, Enum):
    """Supported signal rejection reasons."""

    SETUP_NOT_ENTRY_READY = "SETUP_NOT_ENTRY_READY"
    SETUP_INVALIDATED = "SETUP_INVALIDATED"
    SETUP_EXPIRED = "SETUP_EXPIRED"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_DIRECTION = "INVALID_DIRECTION"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    TARGET_ALREADY_REACHED = "TARGET_ALREADY_REACHED"
    INVALID_STOP_TARGET_RELATIONSHIP = "INVALID_STOP_TARGET_RELATIONSHIP"
    UNSUPPORTED_DIRECTION = "UNSUPPORTED_DIRECTION"
    UNKNOWN_VALIDATION_ERROR = "UNKNOWN_VALIDATION_ERROR"


@dataclass(frozen=True, slots=True)
class SignalValidationResult:
    """Validation result for a signal generation attempt."""

    validation_passed: bool
    validation_errors: tuple[str, ...]
    rejection_reason: SignalRejectionReason | None
    checked_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", ensure_utc(self.checked_at))


@dataclass(frozen=True, slots=True)
class TradeSignal:
    """Replay-safe trade signal record."""

    signal_id: str
    setup_id: str
    symbol: str
    direction: SetupDirection
    action: SignalAction
    status: SignalStatus
    created_at: datetime
    updated_at: datetime
    generated_at: datetime
    entry_reference_type: EntryReferenceType
    entry_reference_price: Decimal | None
    stop_reference_price: Decimal | None
    final_target_price: Decimal | None
    risk_engine_status: str = "NOT_SENT"
    execution_status: str = "NOT_SENT"
    validation_passed: bool = False
    validation_errors: tuple[str, ...] = ()
    rejection_reason: SignalRejectionReason | None = None
    source_state: SetupState | None = None
    source_progress_percent: float = 0.0
    htf_fvg_id: str | None = None
    swing_16m_id: str | None = None
    expansion_16m_id: str | None = None
    fvg_16m_id: str | None = None
    fvg_12m_id: str | None = None
    fvg_8m_id: str | None = None
    one_minute_swing_id: str | None = None
    entry_fvg_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
        object.__setattr__(self, "generated_at", ensure_utc(self.generated_at))
        for field_name in ("entry_reference_price", "stop_reference_price", "final_target_price"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, to_decimal(value))
        if not self.signal_id:
            raise ValueError("signal_id is required")
        if not self.setup_id:
            raise ValueError("setup_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.status is SignalStatus.GENERATED and not self.validation_passed:
            raise ValueError("generated signals require validation_passed")
        if self.status is SignalStatus.REJECTED and self.rejection_reason is None:
            raise ValueError("rejected signals require rejection_reason")


def build_signal_id(
    *,
    setup_id: str,
    generated_at: datetime,
    status: SignalStatus,
    rejection_reason: SignalRejectionReason | None = None,
) -> str:
    """Build deterministic signal ID."""
    raw = "|".join(
        (
            setup_id,
            ensure_utc(generated_at).isoformat(),
            status.value,
            rejection_reason.value if rejection_reason else "",
        )
    )
    return f"sig_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def signal_to_record(signal: TradeSignal) -> dict[str, Any]:
    """Return storage-friendly signal record."""
    return {
        "signal_id": signal.signal_id,
        "setup_id": signal.setup_id,
        "symbol": signal.symbol,
        "direction": signal.direction.value,
        "action": signal.action.value,
        "status": signal.status.value,
        "generated_at": signal.generated_at,
        "entry_reference_type": signal.entry_reference_type.value,
        "entry_reference_price": signal.entry_reference_price,
        "stop_reference_price": signal.stop_reference_price,
        "final_target_price": signal.final_target_price,
        "validation_passed": signal.validation_passed,
        "validation_errors": signal.validation_errors,
        "rejection_reason": signal.rejection_reason.value if signal.rejection_reason else None,
    }
