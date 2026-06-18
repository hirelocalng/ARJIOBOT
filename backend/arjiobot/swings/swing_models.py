"""Data models for ArjioBot swing market structure.

This module contains data-only contracts for the Swing Detection Engine. It does
not contain detection, storage, query, lifecycle transition, or scoring logic.
Those services must be implemented later against the frozen specification.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import Candle, Timeframe, ensure_utc, to_decimal


class SwingType(str, Enum):
    """Supported swing types."""

    HIGH = "HIGH"
    LOW = "LOW"


class SwingStatus(str, Enum):
    """Lifecycle states for a swing."""

    ACTIVE = "ACTIVE"
    BROKEN = "BROKEN"
    MITIGATED = "MITIGATED"


class StructureLabel(str, Enum):
    """Future market structure labels."""

    HIGHER_HIGH = "HH"
    LOWER_HIGH = "LH"
    HIGHER_LOW = "HL"
    LOWER_LOW = "LL"


@dataclass(frozen=True, slots=True)
class SwingSourceCandles:
    """The three candles that form a confirmed swing."""

    left_candle: Candle
    middle_candle: Candle
    right_candle: Candle
    source_candle_ids: tuple[str, str, str]

    def __post_init__(self) -> None:
        """Validate source candle identity and order."""
        if len(self.source_candle_ids) != 3:
            raise ValueError("source_candle_ids must contain exactly three IDs")
        if any(not candle_id for candle_id in self.source_candle_ids):
            raise ValueError("source_candle_ids cannot contain empty IDs")
        if not (
            self.left_candle.timestamp
            < self.middle_candle.timestamp
            < self.right_candle.timestamp
        ):
            raise ValueError("source candles must be strictly ordered by timestamp")

        symbol = self.left_candle.symbol
        timeframe = self.left_candle.timeframe
        for candle in (self.middle_candle, self.right_candle):
            if candle.symbol != symbol:
                raise ValueError("source candles must share the same symbol")
            if candle.timeframe != timeframe:
                raise ValueError("source candles must share the same timeframe")


@dataclass(frozen=True, slots=True)
class Swing:
    """A confirmed swing high or swing low.

    The model stores both candle snapshots and stable source candle IDs so
    backtesting and replay engines can reconstruct swings deterministically.
    """

    swing_id: str
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    candidate_detected_at: datetime
    confirmed_at: datetime
    swing_type: SwingType
    price: Decimal
    candle_index: int
    left_candle: Candle
    middle_candle: Candle
    right_candle: Candle
    source_candle_ids: tuple[str, str, str]
    status: SwingStatus = SwingStatus.ACTIVE
    strength_score: float = 0.0
    previous_swing_high_id: str | None = None
    previous_swing_low_id: str | None = None
    structure_label: StructureLabel | None = None
    parent_swing_id: str | None = None
    is_strategy_candidate: bool = False
    touched_htf_fvg: bool = False
    valid_for_strategy: bool = False
    expansion_confirmed: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status_updated_at: datetime | None = None
    broken_at: datetime | None = None
    broken_by_candle_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize and validate swing data."""
        normalized_symbol = self.symbol.upper()
        parsed_timeframe = Timeframe.parse(self.timeframe)
        timestamp = ensure_utc(self.timestamp)
        candidate_detected_at = ensure_utc(self.candidate_detected_at)
        confirmed_at = ensure_utc(self.confirmed_at)
        created_at = ensure_utc(self.created_at or confirmed_at)
        updated_at = ensure_utc(self.updated_at or created_at)
        status_updated_at = (
            ensure_utc(self.status_updated_at) if self.status_updated_at is not None else None
        )
        broken_at = ensure_utc(self.broken_at) if self.broken_at is not None else None

        object.__setattr__(self, "symbol", normalized_symbol)
        object.__setattr__(self, "timeframe", parsed_timeframe)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "candidate_detected_at", candidate_detected_at)
        object.__setattr__(self, "confirmed_at", confirmed_at)
        object.__setattr__(self, "price", to_decimal(self.price))
        object.__setattr__(self, "strength_score", clamp_strength_score(self.strength_score))
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "status_updated_at", status_updated_at)
        object.__setattr__(self, "broken_at", broken_at)

        self._validate_core_fields()
        self._validate_source_candles()
        self._validate_type_price()
        self._validate_lifecycle_fields()

    @property
    def key(self) -> tuple[str, Timeframe, SwingType, datetime]:
        """Return the unique market-structure key for indexed lookup."""
        return self.symbol, self.timeframe, self.swing_type, self.timestamp

    @property
    def source_candles(self) -> SwingSourceCandles:
        """Return the source candle bundle for this swing."""
        return SwingSourceCandles(
            left_candle=self.left_candle,
            middle_candle=self.middle_candle,
            right_candle=self.right_candle,
            source_candle_ids=self.source_candle_ids,
        )

    def _validate_core_fields(self) -> None:
        """Validate non-candle swing fields."""
        if not self.swing_id:
            raise ValueError("swing_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.candle_index < 1:
            raise ValueError("candle_index must point to a middle candle")
        if self.timestamp != self.middle_candle.timestamp:
            raise ValueError("timestamp must match the middle candle timestamp")
        if self.candidate_detected_at != self.middle_candle.timestamp:
            raise ValueError("candidate_detected_at must match the middle candle timestamp")
        if self.confirmed_at != self.right_candle.end_timestamp:
            raise ValueError("confirmed_at must match the right candle close time")
        if self.confirmed_at <= self.candidate_detected_at:
            raise ValueError("confirmed_at must be after candidate_detected_at")
        if len(self.source_candle_ids) != 3:
            raise ValueError("source_candle_ids must contain exactly three IDs")
        if any(not candle_id for candle_id in self.source_candle_ids):
            raise ValueError("source_candle_ids cannot contain empty IDs")

    def _validate_source_candles(self) -> None:
        """Validate source candle consistency."""
        _ = self.source_candles
        for candle in (self.left_candle, self.middle_candle, self.right_candle):
            if candle.symbol != self.symbol:
                raise ValueError("all swing candles must share the swing symbol")
            if candle.timeframe != self.timeframe:
                raise ValueError("all swing candles must share the swing timeframe")

    def _validate_type_price(self) -> None:
        """Validate the swing price against the middle candle."""
        if self.swing_type is SwingType.HIGH and self.price != self.middle_candle.high:
            raise ValueError("swing high price must equal the middle candle high")
        if self.swing_type is SwingType.LOW and self.price != self.middle_candle.low:
            raise ValueError("swing low price must equal the middle candle low")

    def _validate_lifecycle_fields(self) -> None:
        """Validate lifecycle metadata consistency."""
        if self.status is SwingStatus.BROKEN:
            if self.broken_at is None:
                raise ValueError("broken_at is required when status is BROKEN")
            if self.broken_by_candle_id is None:
                raise ValueError("broken_by_candle_id is required when status is BROKEN")
        if self.broken_at is not None and self.broken_by_candle_id is None:
            raise ValueError("broken_by_candle_id is required when broken_at is set")
        if self.broken_by_candle_id is not None and self.broken_at is None:
            raise ValueError("broken_at is required when broken_by_candle_id is set")


@dataclass(frozen=True, slots=True, init=False)
class SwingHigh(Swing):
    """A confirmed swing high."""

    def __init__(self, **kwargs: Any) -> None:
        """Create a swing high with a fixed ``HIGH`` swing type."""
        kwargs.pop("swing_type", None)
        super(SwingHigh, self).__init__(swing_type=SwingType.HIGH, **kwargs)


@dataclass(frozen=True, slots=True, init=False)
class SwingLow(Swing):
    """A confirmed swing low."""

    def __init__(self, **kwargs: Any) -> None:
        """Create a swing low with a fixed ``LOW`` swing type."""
        kwargs.pop("swing_type", None)
        super(SwingLow, self).__init__(swing_type=SwingType.LOW, **kwargs)


@dataclass(frozen=True, slots=True)
class SwingDetectionResult:
    """Data-only result container for future detector output."""

    swing_highs: tuple[SwingHigh, ...]
    swing_lows: tuple[SwingLow, ...]
    duration_ms: float

    @property
    def all_swings(self) -> tuple[Swing, ...]:
        """Return all swings in timestamp order."""
        return tuple(
            sorted(
                (*self.swing_highs, *self.swing_lows),
                key=lambda swing: (swing.timestamp, swing.swing_type.value),
            )
        )

    @property
    def count(self) -> int:
        """Return the total number of swings in the result."""
        return len(self.swing_highs) + len(self.swing_lows)


def clamp_strength_score(value: float) -> float:
    """Clamp a strength score into the approved 0.0 to 100.0 range."""
    numeric = float(value)
    return max(0.0, min(100.0, numeric))


def build_swing_id(
    *,
    symbol: str,
    timeframe: Timeframe,
    timestamp: datetime,
    swing_type: SwingType,
    source_candle_ids: tuple[str, str, str],
) -> str:
    """Build a deterministic swing ID from stable swing identity fields."""
    parsed_timeframe = Timeframe.parse(timeframe)
    normalized_timestamp = ensure_utc(timestamp).isoformat()
    raw = "|".join(
        (
            symbol.upper(),
            parsed_timeframe.label,
            normalized_timestamp,
            swing_type.value,
            *source_candle_ids,
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"swg_{digest}"


def swing_to_record(swing: Swing) -> dict[str, Any]:
    """Return a storage-friendly record containing required persisted fields."""
    return {
        "swing_id": swing.swing_id,
        "symbol": swing.symbol,
        "timeframe": swing.timeframe.label,
        "timestamp": swing.timestamp,
        "confirmed_at": swing.confirmed_at,
        "swing_type": swing.swing_type.value,
        "price": swing.price,
        "status": swing.status.value,
        "strength_score": swing.strength_score,
        "source_candle_ids": swing.source_candle_ids,
    }
