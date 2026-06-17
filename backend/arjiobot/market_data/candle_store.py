"""In-memory candle storage for market data processing.

The store is intentionally small and deterministic. It keeps candles ordered by
symbol and timeframe so the aggregation and strategy layers can request exact
windows without caring about insertion order.
"""

from __future__ import annotations

import logging
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from threading import RLock
from typing import DefaultDict

from arjiobot.market_data.candle_models import Candle, Timeframe, ensure_utc

logger = logging.getLogger(__name__)

StoreKey = tuple[str, Timeframe]


class CandleStore:
    """Thread-safe ordered store for closed candles."""

    def __init__(self) -> None:
        """Initialize an empty candle store."""
        self._candles: DefaultDict[StoreKey, list[Candle]] = defaultdict(list)
        self._lock = RLock()

    def upsert(self, candle: Candle) -> None:
        """Insert or replace a candle by symbol, timeframe, and timestamp."""
        key = self._key(candle.symbol, candle.timeframe)
        with self._lock:
            bucket = self._candles[key]
            timestamps = [existing.timestamp for existing in bucket]
            index = bisect_left(timestamps, candle.timestamp)
            if index < len(bucket) and bucket[index].timestamp == candle.timestamp:
                bucket[index] = candle
                logger.debug(
                    "Replaced candle",
                    extra={
                        "symbol": candle.symbol,
                        "timeframe": candle.timeframe.label,
                        "timestamp": candle.timestamp.isoformat(),
                    },
                )
                return

            bucket.insert(index, candle)
            logger.debug(
                "Inserted candle",
                extra={
                    "symbol": candle.symbol,
                    "timeframe": candle.timeframe.label,
                    "timestamp": candle.timestamp.isoformat(),
                },
            )

    def bulk_upsert(self, candles: list[Candle]) -> None:
        """Insert or replace multiple candles."""
        for candle in candles:
            self.upsert(candle)

    def get(
        self,
        *,
        symbol: str,
        timeframe: str | int | Timeframe,
        timestamp: datetime,
    ) -> Candle | None:
        """Return one candle by exact timestamp."""
        key = self._key(symbol, timeframe)
        target_timestamp = ensure_utc(timestamp)
        with self._lock:
            bucket = self._candles.get(key, [])
            timestamps = [existing.timestamp for existing in bucket]
            index = bisect_left(timestamps, target_timestamp)
            if index < len(bucket) and bucket[index].timestamp == target_timestamp:
                return bucket[index]
        return None

    def range(
        self,
        *,
        symbol: str,
        timeframe: str | int | Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Return candles where ``start <= timestamp < end``."""
        if ensure_utc(start) >= ensure_utc(end):
            raise ValueError("range start must be before end")

        key = self._key(symbol, timeframe)
        start_timestamp = ensure_utc(start)
        end_timestamp = ensure_utc(end)
        with self._lock:
            bucket = self._candles.get(key, [])
            return [
                candle
                for candle in bucket
                if start_timestamp <= candle.timestamp < end_timestamp
            ]

    def latest(
        self,
        *,
        symbol: str,
        timeframe: str | int | Timeframe,
        limit: int = 1,
    ) -> list[Candle]:
        """Return the latest ``limit`` candles for a symbol and timeframe."""
        if limit < 1:
            raise ValueError("limit must be greater than zero")

        key = self._key(symbol, timeframe)
        with self._lock:
            bucket = self._candles.get(key, [])
            return list(bucket[-limit:])

    def count(self, *, symbol: str, timeframe: str | int | Timeframe) -> int:
        """Return the number of stored candles for a symbol and timeframe."""
        key = self._key(symbol, timeframe)
        with self._lock:
            return len(self._candles.get(key, []))

    def clear(self) -> None:
        """Remove all candles from the store."""
        with self._lock:
            self._candles.clear()
            logger.info("Cleared candle store")

    @staticmethod
    def _key(symbol: str, timeframe: str | int | Timeframe) -> StoreKey:
        """Return the normalized store key."""
        return symbol.upper(), Timeframe.parse(timeframe)
