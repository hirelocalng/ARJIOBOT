"""Data models for ArjioBot expansion candle validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import Timeframe, ensure_utc, to_decimal
from arjiobot.swings.swing_models import SwingType


class ExpansionDirection(str, Enum):
    """Supported expansion directions."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


@dataclass(frozen=True, slots=True)
class ExpansionCandle:
    """A confirmed displacement candle attached to a Swing object."""

    expansion_id: str
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    direction: ExpansionDirection
    swing_id: str
    swing_type: SwingType
    size: Decimal
    expansion_ratio: float
    displacement_distance: Decimal
    displacement_percent: float
    displacement_strength: float
    strength_score: float
    is_fvg_candidate: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Normalize and validate expansion fields."""
        timestamp = ensure_utc(self.timestamp)
        created_at = ensure_utc(self.created_at or timestamp)
        updated_at = ensure_utc(self.updated_at or created_at)

        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "timeframe", Timeframe.parse(self.timeframe))
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "size", to_decimal(self.size))
        object.__setattr__(
            self,
            "displacement_distance",
            to_decimal(self.displacement_distance),
        )
        object.__setattr__(self, "strength_score", clamp_score(self.strength_score))
        object.__setattr__(
            self,
            "displacement_strength",
            clamp_score(self.displacement_strength),
        )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)

        if not self.expansion_id:
            raise ValueError("expansion_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if not self.swing_id:
            raise ValueError("swing_id is required")
        if self.size <= Decimal("0"):
            raise ValueError("size must be greater than zero")
        if self.expansion_ratio <= 0:
            raise ValueError("expansion_ratio must be greater than zero")
        if self.displacement_distance <= Decimal("0"):
            raise ValueError("displacement_distance must be greater than zero")
        if self.displacement_percent <= 0:
            raise ValueError("displacement_percent must be greater than zero")
        if self.direction is ExpansionDirection.BEARISH and self.swing_type is not SwingType.HIGH:
            raise ValueError("bearish expansions must reference swing highs")
        if self.direction is ExpansionDirection.BULLISH and self.swing_type is not SwingType.LOW:
            raise ValueError("bullish expansions must reference swing lows")

    @property
    def key(self) -> tuple[str, Timeframe, datetime, str]:
        """Return the unique lookup key for indexed storage."""
        return self.symbol, self.timeframe, self.timestamp, self.swing_id


@dataclass(frozen=True, slots=True)
class ExpansionDetectionResult:
    """Result container for expansion detection."""

    expansions: tuple[ExpansionCandle, ...]
    rejected_count: int
    duration_ms: float

    @property
    def count(self) -> int:
        """Return the number of detected expansions."""
        return len(self.expansions)


def clamp_score(value: float) -> float:
    """Clamp a score into the approved 0.0 to 100.0 range."""
    numeric = float(value)
    return max(0.0, min(100.0, numeric))


def build_expansion_id(
    *,
    symbol: str,
    timeframe: Timeframe,
    timestamp: datetime,
    direction: ExpansionDirection,
    swing_id: str,
) -> str:
    """Build a deterministic expansion ID from stable identity fields."""
    raw = "|".join(
        (
            symbol.upper(),
            Timeframe.parse(timeframe).label,
            ensure_utc(timestamp).isoformat(),
            direction.value,
            swing_id,
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"exp_{digest}"


def expansion_to_record(expansion: ExpansionCandle) -> dict[str, Any]:
    """Return a storage-friendly expansion record."""
    return {
        "expansion_id": expansion.expansion_id,
        "symbol": expansion.symbol,
        "timeframe": expansion.timeframe.label,
        "timestamp": expansion.timestamp,
        "direction": expansion.direction.value,
        "swing_id": expansion.swing_id,
        "swing_type": expansion.swing_type.value,
        "size": expansion.size,
        "expansion_ratio": expansion.expansion_ratio,
        "displacement_distance": expansion.displacement_distance,
        "displacement_percent": expansion.displacement_percent,
        "displacement_strength": expansion.displacement_strength,
        "strength_score": expansion.strength_score,
        "is_fvg_candidate": expansion.is_fvg_candidate,
    }
