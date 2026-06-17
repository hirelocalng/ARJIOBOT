"""Core candle models used by the market data layer.

The market data layer treats all candles as closed intervals with a start
timestamp and an exclusive end timestamp derived from the candle timeframe.
Synthetic candles are built from strictly aligned 1-minute candles, so this
module keeps timestamp and OHLCV validation close to the data model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Iterable


class CandleStatus(str, Enum):
    """Lifecycle state for a candle."""

    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True, order=True)
class Timeframe:
    """A candle interval measured in whole minutes."""

    minutes: int

    def __post_init__(self) -> None:
        """Validate that the timeframe can be built from 1-minute candles."""
        if self.minutes < 1:
            raise ValueError("timeframe minutes must be greater than zero")

    @property
    def label(self) -> str:
        """Return the normalized display label for the timeframe."""
        return f"{self.minutes}M"

    @property
    def duration(self) -> timedelta:
        """Return the timeframe duration."""
        return timedelta(minutes=self.minutes)

    @classmethod
    def parse(cls, value: str | int | "Timeframe") -> "Timeframe":
        """Parse a timeframe from a label such as ``8M`` or an integer."""
        if isinstance(value, Timeframe):
            return value
        if isinstance(value, int):
            return cls(value)

        normalized = value.strip().upper()
        if not normalized.endswith("M"):
            raise ValueError(f"unsupported timeframe label: {value!r}")

        try:
            minutes = int(normalized[:-1])
        except ValueError as exc:
            raise ValueError(f"invalid timeframe label: {value!r}") from exc

        return cls(minutes)

    def floor_timestamp(self, timestamp: datetime) -> datetime:
        """Return the aligned bucket start for ``timestamp``."""
        aware_timestamp = ensure_utc(timestamp)
        day_start = aware_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed_minutes = int((aware_timestamp - day_start).total_seconds() // 60)
        bucket_minute = elapsed_minutes - (elapsed_minutes % self.minutes)
        return day_start + timedelta(minutes=bucket_minute)

    def is_aligned(self, timestamp: datetime) -> bool:
        """Return whether ``timestamp`` is aligned to this timeframe boundary."""
        return ensure_utc(timestamp) == self.floor_timestamp(timestamp)

    def __str__(self) -> str:
        """Return the normalized timeframe label."""
        return self.label


@dataclass(frozen=True, slots=True)
class Candle:
    """An OHLCV candle for a symbol and timeframe."""

    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")
    status: CandleStatus = CandleStatus.CLOSED
    source_count: int = 1
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize and validate candle values."""
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        object.__setattr__(self, "timeframe", Timeframe.parse(self.timeframe))
        object.__setattr__(self, "open", to_decimal(self.open))
        object.__setattr__(self, "high", to_decimal(self.high))
        object.__setattr__(self, "low", to_decimal(self.low))
        object.__setattr__(self, "close", to_decimal(self.close))
        object.__setattr__(self, "volume", to_decimal(self.volume))

        if not self.symbol:
            raise ValueError("symbol is required")
        if self.timestamp.second != 0 or self.timestamp.microsecond != 0:
            raise ValueError("candle timestamp must be minute aligned")
        if not self.timeframe.is_aligned(self.timestamp):
            raise ValueError(
                f"timestamp {self.timestamp.isoformat()} is not aligned to {self.timeframe.label}"
            )
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be greater than or equal to open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be less than or equal to open, close, and high")
        if self.volume < Decimal("0"):
            raise ValueError("volume cannot be negative")
        if self.source_count < 1:
            raise ValueError("source_count must be greater than zero")

    @property
    def end_timestamp(self) -> datetime:
        """Return the exclusive end timestamp for the candle."""
        return self.timestamp + self.timeframe.duration

    @property
    def range_size(self) -> Decimal:
        """Return the candle high-low range."""
        return self.high - self.low

    def is_one_minute(self) -> bool:
        """Return whether the candle is a closed 1-minute candle."""
        return self.timeframe.minutes == 1


def ensure_utc(timestamp: datetime) -> datetime:
    """Return ``timestamp`` as a timezone-aware UTC datetime."""
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def to_decimal(value: Decimal | int | float | str) -> Decimal:
    """Convert numeric values to ``Decimal`` without float representation noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def build_synthetic_candle(
    *,
    symbol: str,
    timeframe: Timeframe,
    candles: Iterable[Candle],
) -> Candle:
    """Build one synthetic candle from ordered 1-minute candles.

    Raises:
        ValueError: If candles are empty, incomplete, mixed-symbol, not 1-minute,
            or not strictly consecutive from the expected timeframe boundary.
    """
    source_candles = list(candles)
    if not source_candles:
        raise ValueError("cannot build synthetic candle from an empty sequence")

    parsed_timeframe = Timeframe.parse(timeframe)
    expected_count = parsed_timeframe.minutes
    if len(source_candles) != expected_count:
        raise ValueError(
            f"{parsed_timeframe.label} candle requires {expected_count} one-minute candles"
        )

    ordered = sorted(source_candles, key=lambda candle: candle.timestamp)
    start = ordered[0].timestamp
    if not parsed_timeframe.is_aligned(start):
        raise ValueError(f"first source candle is not aligned to {parsed_timeframe.label}")

    normalized_symbol = symbol.upper()
    for index, candle in enumerate(ordered):
        if candle.symbol != normalized_symbol:
            raise ValueError("source candles must share the requested symbol")
        if not candle.is_one_minute():
            raise ValueError("synthetic candles can only be built from 1-minute candles")
        if candle.status is not CandleStatus.CLOSED:
            raise ValueError("synthetic candles require closed source candles")
        expected_timestamp = start + timedelta(minutes=index)
        if candle.timestamp != expected_timestamp:
            raise ValueError("source candles must be strictly consecutive")

    return Candle(
        symbol=normalized_symbol,
        timeframe=parsed_timeframe,
        timestamp=start,
        open=ordered[0].open,
        high=max(candle.high for candle in ordered),
        low=min(candle.low for candle in ordered),
        close=ordered[-1].close,
        volume=sum((candle.volume for candle in ordered), Decimal("0")),
        status=CandleStatus.CLOSED,
        source_count=len(ordered),
        metadata={"source_timeframe": "1M"},
    )
