"""Synthetic timeframe configuration and validation.

The bot starts with 8M, 12M, and 16M synthetic candles, while also accepting
10M, 15M, 20M, and any future whole-minute interval that can be built from
closed 1-minute candles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from arjiobot.market_data.candle_models import Timeframe

logger = logging.getLogger(__name__)

BASE_TIMEFRAME = Timeframe(1)
DEFAULT_SYNTHETIC_TIMEFRAMES: tuple[Timeframe, ...] = (
    Timeframe(8),
    Timeframe(12),
    Timeframe(16),
)
SUPPORTED_COMMON_TIMEFRAMES: tuple[Timeframe, ...] = (
    Timeframe(8),
    Timeframe(10),
    Timeframe(12),
    Timeframe(15),
    Timeframe(16),
    Timeframe(20),
)


@dataclass(slots=True)
class SyntheticTimeframeRegistry:
    """Registry for synthetic timeframe combinations."""

    timeframes: set[Timeframe] = field(default_factory=lambda: set(DEFAULT_SYNTHETIC_TIMEFRAMES))

    def __post_init__(self) -> None:
        """Normalize registry input into validated ``Timeframe`` objects."""
        self.timeframes = {Timeframe.parse(timeframe) for timeframe in self.timeframes}
        for timeframe in self.timeframes:
            self.validate(timeframe)

    def register(self, timeframe: str | int | Timeframe) -> Timeframe:
        """Register and return a synthetic timeframe."""
        parsed = Timeframe.parse(timeframe)
        self.validate(parsed)
        self.timeframes.add(parsed)
        logger.info("Registered synthetic timeframe", extra={"timeframe": parsed.label})
        return parsed

    def unregister(self, timeframe: str | int | Timeframe) -> None:
        """Remove a synthetic timeframe if it exists."""
        parsed = Timeframe.parse(timeframe)
        self.timeframes.discard(parsed)
        logger.info("Unregistered synthetic timeframe", extra={"timeframe": parsed.label})

    def extend(self, timeframes: Iterable[str | int | Timeframe]) -> tuple[Timeframe, ...]:
        """Register multiple synthetic timeframes and return all registered values."""
        for timeframe in timeframes:
            self.register(timeframe)
        return self.list()

    def list(self) -> tuple[Timeframe, ...]:
        """Return registered timeframes sorted by duration."""
        return tuple(sorted(self.timeframes, key=lambda timeframe: timeframe.minutes))

    def contains(self, timeframe: str | int | Timeframe) -> bool:
        """Return whether the registry contains ``timeframe``."""
        return Timeframe.parse(timeframe) in self.timeframes

    @staticmethod
    def validate(timeframe: Timeframe) -> None:
        """Validate that a timeframe can be generated from 1-minute candles."""
        if timeframe.minutes <= BASE_TIMEFRAME.minutes:
            raise ValueError("synthetic timeframes must be greater than 1 minute")


def default_registry() -> SyntheticTimeframeRegistry:
    """Return a registry with the bot default synthetic timeframes."""
    return SyntheticTimeframeRegistry()
