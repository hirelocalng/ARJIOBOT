"""Data models for the ArjioBot Setup Tracker."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import ensure_utc, to_decimal


class SetupDirection(str, Enum):
    """Supported setup directions."""

    BEARISH = "BEARISH"
    BULLISH = "BULLISH"


class SetupState(str, Enum):
    """Setup lifecycle states."""

    WATCHING_HTF_FVG = "WATCHING_HTF_FVG"
    HTF_FVG_TAPPED = "HTF_FVG_TAPPED"
    SWING_16M_CONFIRMED = "SWING_16M_CONFIRMED"
    EXPANSION_16M_CONFIRMED = "EXPANSION_16M_CONFIRMED"
    FVG_16M_CONFIRMED = "FVG_16M_CONFIRMED"
    FVG_12M_CONFIRMED = "FVG_12M_CONFIRMED"
    FVG_8M_CONFIRMED = "FVG_8M_CONFIRMED"
    WAITING_FOR_12M_RETRACE = "WAITING_FOR_12M_RETRACE"
    ONE_MINUTE_CONFIRMATION_ACTIVE = "ONE_MINUTE_CONFIRMATION_ACTIVE"
    ONE_MINUTE_SWING_CONFIRMED = "ONE_MINUTE_SWING_CONFIRMED"
    ONE_MINUTE_FVG_CONFIRMED = "ONE_MINUTE_FVG_CONFIRMED"
    ENTRY_READY = "ENTRY_READY"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


class SetupStatus(str, Enum):
    """High-level setup status."""

    ACTIVE = "ACTIVE"
    ENTRY_READY = "ENTRY_READY"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


class InvalidationReason(str, Enum):
    """Supported invalidation reasons."""

    HTF_FVG_INVALID = "HTF_FVG_INVALID"
    SWING_NOT_CONFIRMED = "SWING_NOT_CONFIRMED"
    EXPANSION_NOT_CONFIRMED = "EXPANSION_NOT_CONFIRMED"
    FVG_16M_NOT_FOUND = "FVG_16M_NOT_FOUND"
    FVG_12M_NOT_FOUND = "FVG_12M_NOT_FOUND"
    FVG_8M_NOT_FOUND = "FVG_8M_NOT_FOUND"
    FVG_OUTSIDE_16M_LEG = "FVG_OUTSIDE_16M_LEG"
    RETRACE_WINDOW_EXPIRED = "RETRACE_WINDOW_EXPIRED"
    CLOSE_ABOVE_12M_FVG = "CLOSE_ABOVE_12M_FVG"
    CLOSE_BELOW_12M_FVG = "CLOSE_BELOW_12M_FVG"
    THIRD_HIGH_INSIDE_12M_FVG = "THIRD_HIGH_INSIDE_12M_FVG"
    THIRD_LOW_INSIDE_12M_FVG = "THIRD_LOW_INSIDE_12M_FVG"
    CONSOLIDATION_INSIDE_12M_FVG = "CONSOLIDATION_INSIDE_12M_FVG"
    PRICE_REACHED_TARGET_BEFORE_ENTRY = "PRICE_REACHED_TARGET_BEFORE_ENTRY"
    SETUP_EXPIRED = "SETUP_EXPIRED"
    MANUAL_INVALIDATION = "MANUAL_INVALIDATION"


@dataclass(frozen=True, slots=True)
class StateHistoryEntry:
    """One deterministic setup state transition."""

    from_state: SetupState | None
    to_state: SetupState
    changed_at: datetime
    reason: str | None = None
    triggering_object_type: str | None = None
    triggering_object_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "changed_at", ensure_utc(self.changed_at))


@dataclass(frozen=True, slots=True)
class Setup:
    """A tracked Arjio setup."""

    setup_id: str
    symbol: str
    direction: SetupDirection
    current_state: SetupState
    progress_percent: float
    status: SetupStatus
    created_at: datetime
    updated_at: datetime
    invalidated_at: datetime | None = None
    invalidation_reason: InvalidationReason | None = None
    last_valid_stage: str | None = None
    completed_at: datetime | None = None
    htf_fvg_id: str | None = None
    swing_16m_id: str | None = None
    expansion_16m_id: str | None = None
    fvg_16m_id: str | None = None
    fvg_12m_id: str | None = None
    fvg_8m_id: str | None = None
    retrace_tap_candle_id: str | None = None
    one_minute_swing_id: str | None = None
    one_minute_fvg_ids: tuple[str, ...] = ()
    entry_fvg_id: str | None = None
    stop_reference_price: Decimal | None = None
    target_a_price: Decimal | None = None
    target_b_price: Decimal | None = None
    final_target_price: Decimal | None = None
    time_remaining: str | None = None
    state_history: tuple[StateHistoryEntry, ...] = ()
    watched_timeframes: tuple[str, ...] = ("30M", "1H", "16M", "12M", "8M", "1M")
    # None while a real ENTRY_READY setup (_setup_from_trade) is still sitting
    # in IN PROGRESS awaiting live_automation's verdict ("pending execution") -
    # set to one of TERMINAL_EXECUTION_STATES the moment that verdict is in
    # (see live_automation.py's _process_setup and should_leave_in_progress
    # below). Never set for an attempt-tracer diagnostic row (no real
    # execution is ever attempted for those).
    execution_status: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
        object.__setattr__(self, "progress_percent", clamp_progress(self.progress_percent))
        if self.invalidated_at is not None:
            object.__setattr__(self, "invalidated_at", ensure_utc(self.invalidated_at))
        if self.completed_at is not None:
            object.__setattr__(self, "completed_at", ensure_utc(self.completed_at))
        for field_name in ("stop_reference_price", "target_a_price", "target_b_price", "final_target_price"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, to_decimal(value))
        self._validate()

    def _validate(self) -> None:
        if not self.setup_id:
            raise ValueError("setup_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.current_state is SetupState.INVALIDATED:
            if self.status is not SetupStatus.INVALIDATED:
                raise ValueError("invalidated setup status must be INVALIDATED")
            if self.invalidated_at is None or self.invalidation_reason is None:
                raise ValueError("invalidated setups require reason and timestamp")
        if self.current_state is SetupState.ENTRY_READY and self.status is not SetupStatus.ENTRY_READY:
            raise ValueError("entry-ready setup status must be ENTRY_READY")
        if self.progress_percent >= 100.0 and self.invalidation_reason is not None:
            raise ValueError("a setup cannot be both 100% complete and invalidated")


@dataclass(frozen=True, slots=True)
class SetupRadarItem:
    """Dashboard-ready setup radar row."""

    setup_id: str
    symbol: str
    direction: SetupDirection
    current_state: SetupState
    progress_percent: float
    missing_requirements: tuple[str, ...]
    invalidation_reason: InvalidationReason | None
    time_remaining: str | None
    watched_timeframes: tuple[str, ...]
    latest_relevant_price: Decimal | None
    target_reference: Decimal | None
    stop_reference: Decimal | None


def clamp_progress(value: float) -> float:
    """Clamp progress to 0.0 through 100.0."""
    return max(0.0, min(100.0, float(value)))


# "Pending execution" (execution_status is None) is deliberately NOT in this
# set - it must never make a setup leave IN PROGRESS on its own. A setup
# leaves IN PROGRESS only once one of these is reached: a confirmed live
# trade (trade_opened), an explicit execution-side rejection (rejected/
# risk_blocked/no_margin), or it became invalidated/expired through the
# existing, separate invalidation/staleness paths.
TERMINAL_EXECUTION_STATES = frozenset({"trade_opened", "rejected", "risk_blocked", "no_margin", "invalidated", "expired"})


def should_leave_in_progress(setup: Setup) -> bool:
    """Whether `setup` is done being tracked in IN PROGRESS (state.setups) -
    True once execution_status reaches one of TERMINAL_EXECUTION_STATES,
    False while it is still None ("pending execution", 100% complete but
    execution has not yet confirmed or rejected it)."""
    return setup.execution_status in TERMINAL_EXECUTION_STATES


def build_setup_id(
    *,
    symbol: str,
    direction: SetupDirection,
    created_at: datetime,
    htf_fvg_id: str | None = None,
) -> str:
    """Build a deterministic setup ID."""
    raw = "|".join(
        (
            symbol.upper(),
            direction.value,
            ensure_utc(created_at).isoformat(),
            htf_fvg_id or "",
        )
    )
    return f"set_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def setup_to_record(setup: Setup) -> dict[str, Any]:
    """Return a storage-friendly setup record."""
    return {
        "setup_id": setup.setup_id,
        "symbol": setup.symbol,
        "direction": setup.direction.value,
        "current_state": setup.current_state.value,
        "progress_percent": setup.progress_percent,
        "status": setup.status.value,
        "invalidation_reason": setup.invalidation_reason.value if setup.invalidation_reason else None,
        "last_valid_stage": setup.last_valid_stage,
        "htf_fvg_id": setup.htf_fvg_id,
        "swing_16m_id": setup.swing_16m_id,
        "expansion_16m_id": setup.expansion_16m_id,
        "fvg_16m_id": setup.fvg_16m_id,
        "fvg_12m_id": setup.fvg_12m_id,
        "fvg_8m_id": setup.fvg_8m_id,
        "entry_fvg_id": setup.entry_fvg_id,
        "final_target_price": setup.final_target_price,
        "stop_reference_price": setup.stop_reference_price,
    }
