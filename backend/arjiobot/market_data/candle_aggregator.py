"""Aggregation of closed 1-minute candles into synthetic timeframes."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import DefaultDict

from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe, build_synthetic_candle
from arjiobot.market_data.candle_store import CandleStore
from arjiobot.market_data.synthetic_timeframes import SyntheticTimeframeRegistry, default_registry

logger = logging.getLogger(__name__)


class CandleAggregator:
    """Stateful generator for synthetic candles built from 1-minute candles."""

    def __init__(
        self,
        *,
        store: CandleStore | None = None,
        registry: SyntheticTimeframeRegistry | None = None,
    ) -> None:
        """Initialize the aggregator with a store and timeframe registry."""
        self.store = store or CandleStore()
        self.registry = registry or default_registry()
        self._buffers: DefaultDict[tuple[str, Timeframe, datetime], dict[datetime, Candle]] = defaultdict(dict)

    def ingest(self, candle: Candle) -> list[Candle]:
        """Ingest a closed 1-minute candle and return completed synthetic candles."""
        self._validate_source_candle(candle)
        self.store.upsert(candle)

        generated: list[Candle] = []
        for timeframe in self.registry.list():
            bucket_start = timeframe.floor_timestamp(candle.timestamp)
            buffer_key = (candle.symbol, timeframe, bucket_start)
            self._buffers[buffer_key][candle.timestamp] = candle

            if len(self._buffers[buffer_key]) != timeframe.minutes:
                logger.debug(
                    "Buffered source candle",
                    extra={
                        "symbol": candle.symbol,
                        "timeframe": timeframe.label,
                        "bucket_start": bucket_start.isoformat(),
                        "count": len(self._buffers[buffer_key]),
                    },
                )
                continue

            source_candles = list(self._buffers[buffer_key].values())
            synthetic = build_synthetic_candle(
                symbol=candle.symbol,
                timeframe=timeframe,
                candles=source_candles,
            )
            self.store.upsert(synthetic)
            generated.append(synthetic)
            del self._buffers[buffer_key]
            logger.info(
                "Generated synthetic candle",
                extra={
                    "symbol": synthetic.symbol,
                    "timeframe": synthetic.timeframe.label,
                    "timestamp": synthetic.timestamp.isoformat(),
                    "source_count": synthetic.source_count,
                },
            )

        return generated

    def ingest_many(self, candles: list[Candle]) -> list[Candle]:
        """Ingest candles in timestamp order and return generated synthetic candles."""
        generated: list[Candle] = []
        for candle in sorted(candles, key=lambda item: item.timestamp):
            generated.extend(self.ingest(candle))
        return generated

    def register_timeframe(self, timeframe: str | int | Timeframe) -> Timeframe:
        """Register an additional synthetic timeframe."""
        return self.registry.register(timeframe)

    def buffered_count(
        self,
        *,
        symbol: str,
        timeframe: str | int | Timeframe,
        bucket_start: datetime,
    ) -> int:
        """Return source candle count buffered for a synthetic bucket."""
        parsed_timeframe = Timeframe.parse(timeframe)
        key = (symbol.upper(), parsed_timeframe, parsed_timeframe.floor_timestamp(bucket_start))
        return len(self._buffers.get(key, {}))

    @staticmethod
    def _validate_source_candle(candle: Candle) -> None:
        """Validate the candle can be used as a source for synthetic candles."""
        if not candle.is_one_minute():
            raise ValueError("aggregator only accepts 1-minute source candles")
        if candle.status is not CandleStatus.CLOSED:
            raise ValueError("aggregator only accepts closed source candles")
