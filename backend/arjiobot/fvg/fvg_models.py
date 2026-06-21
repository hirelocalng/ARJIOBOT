"""Data models for the ArjioBot FVG Engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import Timeframe, ensure_utc, to_decimal


class FVGDirection(str, Enum):
    """Supported FVG directions."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class FVGLifecycleState(str, Enum):
    """Supported FVG lifecycle states."""

    ACTIVE = "ACTIVE"
    TAPPED = "TAPPED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


FVGStatus = FVGLifecycleState


@dataclass(frozen=True, slots=True)
class FairValueGap:
    """A replay-safe Fair Value Gap record."""

    fvg_id: str
    symbol: str
    timeframe: Timeframe
    direction: FVGDirection
    timestamp: datetime
    confirmed_at: datetime
    c1_id: str
    c2_id: str
    c3_id: str
    c1_timestamp: datetime
    c2_timestamp: datetime
    c3_timestamp: datetime
    upper_boundary: Decimal
    lower_boundary: Decimal
    gap_size: Decimal
    gap_size_percent: float
    status: FVGLifecycleState = FVGLifecycleState.ACTIVE
    lifecycle_state: FVGLifecycleState = FVGLifecycleState.ACTIVE
    touched: bool = False
    touch_count: int = 0
    first_touched_at: datetime | None = None
    last_touched_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    related_swing_id: str | None = None
    related_expansion_id: str | None = None
    is_strategy_fvg: bool = False
    is_htf_fvg: bool = False
    is_entry_fvg: bool = False
    is_target_fvg: bool = False
    strength_score: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    fvg_completion_candle_low: Decimal | None = None
    fvg_completion_candle_high: Decimal | None = None

    def __post_init__(self) -> None:
        """Normalize and validate the FVG model."""
        timestamp = ensure_utc(self.timestamp)
        confirmed_at = ensure_utc(self.confirmed_at)
        created_at = ensure_utc(self.created_at or confirmed_at)
        updated_at = ensure_utc(self.updated_at or created_at)

        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "timeframe", Timeframe.parse(self.timeframe))
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "confirmed_at", confirmed_at)
        object.__setattr__(self, "c1_timestamp", ensure_utc(self.c1_timestamp))
        object.__setattr__(self, "c2_timestamp", ensure_utc(self.c2_timestamp))
        object.__setattr__(self, "c3_timestamp", ensure_utc(self.c3_timestamp))
        object.__setattr__(self, "upper_boundary", to_decimal(self.upper_boundary))
        object.__setattr__(self, "lower_boundary", to_decimal(self.lower_boundary))
        object.__setattr__(self, "gap_size", to_decimal(self.gap_size))
        object.__setattr__(self, "strength_score", clamp_score(self.strength_score))
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        if self.first_touched_at is not None:
            object.__setattr__(self, "first_touched_at", ensure_utc(self.first_touched_at))
        if self.last_touched_at is not None:
            object.__setattr__(self, "last_touched_at", ensure_utc(self.last_touched_at))
        if self.invalidated_at is not None:
            object.__setattr__(self, "invalidated_at", ensure_utc(self.invalidated_at))
        if self.fvg_completion_candle_low is not None:
            object.__setattr__(
                self,
                "fvg_completion_candle_low",
                to_decimal(self.fvg_completion_candle_low),
            )
        if self.fvg_completion_candle_high is not None:
            object.__setattr__(
                self,
                "fvg_completion_candle_high",
                to_decimal(self.fvg_completion_candle_high),
            )

        self._validate()

    @property
    def key(self) -> tuple[str, Timeframe, FVGDirection, datetime]:
        """Return the indexed market key."""
        return self.symbol, self.timeframe, self.direction, self.timestamp

    def _validate(self) -> None:
        """Validate field consistency."""
        if not self.fvg_id:
            raise ValueError("fvg_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if any(not value for value in (self.c1_id, self.c2_id, self.c3_id)):
            raise ValueError("candle IDs are required")
        if not (self.c1_timestamp < self.c2_timestamp < self.c3_timestamp):
            raise ValueError("FVG candle timestamps must be strictly ordered")
        if self.timestamp != self.c2_timestamp:
            raise ValueError("timestamp must match C2 timestamp")
        if self.confirmed_at <= self.c2_timestamp:
            raise ValueError("confirmed_at must be after C2")
        if self.upper_boundary <= self.lower_boundary:
            raise ValueError("upper_boundary must be above lower_boundary")
        if self.gap_size != self.upper_boundary - self.lower_boundary:
            raise ValueError("gap_size must equal upper_boundary - lower_boundary")
        if self.gap_size <= Decimal("0"):
            raise ValueError("gap_size must be positive")
        if self.touch_count < 0:
            raise ValueError("touch_count cannot be negative")
        if self.touched and self.touch_count < 1:
            raise ValueError("touched FVGs require touch_count")
        if self.touch_count and self.first_touched_at is None:
            raise ValueError("touch_count requires first_touched_at")
        if self.lifecycle_state is FVGLifecycleState.INVALIDATED:
            if self.invalidated_at is None:
                raise ValueError("invalidated_at is required when invalidated")
            if not self.invalidation_reason:
                raise ValueError("invalidation_reason is required when invalidated")
        if self.status is not self.lifecycle_state:
            raise ValueError("status and lifecycle_state must stay in sync")


@dataclass(frozen=True, slots=True)
class FVGDetectionResult:
    """Detection result container."""

    fvgs: tuple[FairValueGap, ...]
    rejected_count: int
    duration_ms: float

    @property
    def count(self) -> int:
        """Return detected FVG count."""
        return len(self.fvgs)


def clamp_score(value: float) -> float:
    """Clamp score to 0.0 through 100.0."""
    numeric = float(value)
    return max(0.0, min(100.0, numeric))


def build_fvg_id(
    *,
    symbol: str,
    timeframe: Timeframe,
    direction: FVGDirection,
    c1_id: str,
    c2_id: str,
    c3_id: str,
    related_expansion_id: str | None = None,
) -> str:
    """Build a deterministic FVG ID."""
    raw = "|".join(
        (
            symbol.upper(),
            Timeframe.parse(timeframe).label,
            direction.value,
            c1_id,
            c2_id,
            c3_id,
            related_expansion_id or "",
        )
    )
    return f"fvg_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def fvg_to_record(fvg: FairValueGap) -> dict[str, Any]:
    """Return a storage-friendly record."""
    return {
        "fvg_id": fvg.fvg_id,
        "symbol": fvg.symbol,
        "timeframe": fvg.timeframe.label,
        "direction": fvg.direction.value,
        "timestamp": fvg.timestamp,
        "confirmed_at": fvg.confirmed_at,
        "upper_boundary": fvg.upper_boundary,
        "lower_boundary": fvg.lower_boundary,
        "gap_size": fvg.gap_size,
        "status": fvg.status.value,
        "lifecycle_state": fvg.lifecycle_state.value,
        "touched": fvg.touched,
        "touch_count": fvg.touch_count,
        "related_swing_id": fvg.related_swing_id,
        "related_expansion_id": fvg.related_expansion_id,
        "is_strategy_fvg": fvg.is_strategy_fvg,
        "is_htf_fvg": fvg.is_htf_fvg,
        "is_entry_fvg": fvg.is_entry_fvg,
        "is_target_fvg": fvg.is_target_fvg,
        "strength_score": fvg.strength_score,
    }
