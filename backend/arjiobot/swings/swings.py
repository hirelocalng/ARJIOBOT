"""Swing Detection Engine.

This module implements the frozen v1 Swing Detection Engine service. It only
detects and manages swing market structure. It does not perform FVG, expansion,
strategy, risk, or execution logic.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict, deque
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import DefaultDict, Iterable, Protocol, Sequence

from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe, ensure_utc
from arjiobot.swings.swing_models import (
    StructureLabel,
    Swing,
    SwingDetectionResult,
    SwingHigh,
    SwingLow,
    SwingStatus,
    SwingType,
    build_swing_id,
)

logger = logging.getLogger(__name__)

StreamKey = tuple[str, Timeframe]


class SwingDefinition(Protocol):
    """Interface for pluggable swing definitions."""

    window_size: int

    def is_swing_high(self, candles: Sequence[Candle]) -> bool:
        """Return whether the candle window forms a swing high."""

    def is_swing_low(self, candles: Sequence[Candle]) -> bool:
        """Return whether the candle window forms a swing low."""


class ThreeCandleSwingDefinition:
    """Strict three-candle Arjio swing definition."""

    window_size = 3

    def is_swing_high(self, candles: Sequence[Candle]) -> bool:
        """Return whether C2 is higher than both neighboring candle highs."""
        self._validate_window(candles)
        left, middle, right = candles
        return middle.high > left.high and middle.high > right.high

    def is_swing_low(self, candles: Sequence[Candle]) -> bool:
        """Return whether C2 is lower than both neighboring candle lows."""
        self._validate_window(candles)
        left, middle, right = candles
        return middle.low < left.low and middle.low < right.low

    def _validate_window(self, candles: Sequence[Candle]) -> None:
        """Validate the window size for the three-candle definition."""
        if len(candles) != self.window_size:
            raise ValueError("three-candle swing detection requires exactly three candles")


class SwingStrengthScorer(Protocol):
    """Interface for pluggable swing strength scorers."""

    def score(
        self,
        *,
        swing_type: SwingType,
        source_candles: Sequence[Candle],
        previous_swing_high: Swing | None,
        previous_swing_low: Swing | None,
    ) -> float:
        """Return a strength score from 0.0 to 100.0."""


class DefaultSwingStrengthScorer:
    """Initial non-zero scorer required by the frozen specification."""

    def score(
        self,
        *,
        swing_type: SwingType,
        source_candles: Sequence[Candle],
        previous_swing_high: Swing | None,
        previous_swing_low: Swing | None,
    ) -> float:
        """Score a swing using timeframe, distance, range, and displacement."""
        left, middle, right = source_candles
        relevant_previous = (
            previous_swing_high if swing_type is SwingType.HIGH else previous_swing_low
        )
        timeframe_score = min(30.0, float(middle.timeframe.minutes) / 60.0 * 30.0)
        middle_range = float(middle.range_size)
        neighbor_average_range = (
            float(left.range_size) + float(right.range_size)
        ) / 2.0
        range_score = min(25.0, (middle_range / neighbor_average_range) * 12.5) if neighbor_average_range else 0.0

        displacement = abs(float(middle.close - left.open))
        displacement_score = min(25.0, (displacement / middle_range) * 25.0) if middle_range else 0.0

        distance_score = 5.0
        if relevant_previous is not None:
            distance = abs(float(middle.high - relevant_previous.price)) if swing_type is SwingType.HIGH else abs(float(middle.low - relevant_previous.price))
            distance_score = min(20.0, (distance / middle_range) * 10.0) if middle_range else 5.0

        return max(0.0, min(100.0, timeframe_score + range_score + displacement_score + distance_score))


class SwingStore:
    """Indexed in-memory store for confirmed swings."""

    def __init__(self) -> None:
        """Initialize an empty swing store."""
        self._by_id: dict[str, Swing] = {}
        self._ids_by_symbol_timeframe: DefaultDict[tuple[str, Timeframe], list[str]] = defaultdict(list)

    def upsert(self, swing: Swing) -> Swing:
        """Insert or replace a swing."""
        key = (swing.symbol, swing.timeframe)
        if swing.swing_id not in self._by_id:
            self._ids_by_symbol_timeframe[key].append(swing.swing_id)
        self._by_id[swing.swing_id] = swing
        self._ids_by_symbol_timeframe[key].sort(
            key=lambda swing_id: (
                self._by_id[swing_id].timestamp,
                self._by_id[swing_id].swing_type.value,
            )
        )
        return swing

    def get_swing_by_id(self, swing_id: str) -> Swing | None:
        """Return a swing by ID."""
        return self._by_id.get(swing_id)

    def latest(
        self,
        *,
        symbol: str,
        timeframe: str | int | Timeframe,
        swing_type: SwingType,
    ) -> Swing | None:
        """Return the latest swing of a type for a symbol/timeframe."""
        swings = self.get_swings_for_timeframe(
            symbol=symbol,
            timeframe=timeframe,
            swing_type=swing_type,
        )
        return swings[-1] if swings else None

    def get_active_swings(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
    ) -> tuple[Swing, ...]:
        """Return active swings, optionally filtered by symbol and timeframe."""
        normalized_symbol = symbol.upper() if symbol else None
        parsed_timeframe = Timeframe.parse(timeframe) if timeframe is not None else None
        return tuple(
            sorted(
                (
                    swing
                    for swing in self._by_id.values()
                    if swing.status is SwingStatus.ACTIVE
                    and (normalized_symbol is None or swing.symbol == normalized_symbol)
                    and (parsed_timeframe is None or swing.timeframe == parsed_timeframe)
                ),
                key=lambda swing: (swing.symbol, swing.timeframe.minutes, swing.timestamp),
            )
        )

    def get_swings_between(
        self,
        *,
        symbol: str,
        timeframe: str | int | Timeframe,
        start: datetime,
        end: datetime,
        swing_type: SwingType | None = None,
        status: SwingStatus | None = None,
    ) -> tuple[Swing, ...]:
        """Return swings where ``start <= timestamp < end``."""
        if ensure_utc(start) >= ensure_utc(end):
            raise ValueError("start must be before end")
        return tuple(
            swing
            for swing in self.get_swings_for_timeframe(
                symbol=symbol,
                timeframe=timeframe,
                swing_type=swing_type,
                status=status,
            )
            if ensure_utc(start) <= swing.timestamp < ensure_utc(end)
        )

    def get_swings_for_timeframe(
        self,
        *,
        symbol: str,
        timeframe: str | int | Timeframe,
        swing_type: SwingType | None = None,
        status: SwingStatus | None = None,
        limit: int | None = None,
    ) -> tuple[Swing, ...]:
        """Return swings for a symbol and timeframe."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be greater than zero")
        key = (symbol.upper(), Timeframe.parse(timeframe))
        swings = [
            self._by_id[swing_id]
            for swing_id in self._ids_by_symbol_timeframe.get(key, [])
            if (swing_type is None or self._by_id[swing_id].swing_type is swing_type)
            and (status is None or self._by_id[swing_id].status is status)
        ]
        if limit is not None:
            swings = swings[-limit:]
        return tuple(swings)

    def replace(self, swing: Swing) -> Swing:
        """Replace an existing swing."""
        if swing.swing_id not in self._by_id:
            raise KeyError(f"unknown swing_id: {swing.swing_id}")
        self._by_id[swing.swing_id] = swing
        return swing

    def count(self) -> int:
        """Return the number of stored swings."""
        return len(self._by_id)


class SwingDetectionEngine:
    """Detect and manage Arjio swing market structure."""

    def __init__(
        self,
        *,
        definition: SwingDefinition | None = None,
        scorer: SwingStrengthScorer | None = None,
        store: SwingStore | None = None,
    ) -> None:
        """Initialize the swing engine."""
        self.definition = definition or ThreeCandleSwingDefinition()
        self.scorer = scorer or DefaultSwingStrengthScorer()
        self.store = store or SwingStore()
        self._stream_buffers: DefaultDict[StreamKey, deque[Candle]] = defaultdict(
            lambda: deque(maxlen=self.definition.window_size)
        )
        self._stream_indexes: DefaultDict[StreamKey, int] = defaultdict(int)

    def detect_swing_highs(self, candles: Sequence[Candle]) -> tuple[SwingHigh, ...]:
        """Detect swing highs in historical candles."""
        return self.detect_all_swings(candles).swing_highs

    def detect_swing_lows(self, candles: Sequence[Candle]) -> tuple[SwingLow, ...]:
        """Detect swing lows in historical candles."""
        return self.detect_all_swings(candles).swing_lows

    def detect_all_swings(self, candles: Sequence[Candle]) -> SwingDetectionResult:
        """Detect all swings in one O(n) historical pass."""
        started_at = perf_counter()
        ordered = self._prepare_historical_candles(candles)
        highs: list[SwingHigh] = []
        lows: list[SwingLow] = []

        if len(ordered) < self.definition.window_size:
            return SwingDetectionResult(swing_highs=(), swing_lows=(), duration_ms=0.0)

        for middle_index in range(1, len(ordered) - 1):
            window = ordered[middle_index - 1 : middle_index + 2]
            self._validate_consecutive_window(window)
            previous_high = self.get_latest_swing_high(
                symbol=window[1].symbol,
                timeframe=window[1].timeframe,
            )
            previous_low = self.get_latest_swing_low(
                symbol=window[1].symbol,
                timeframe=window[1].timeframe,
            )

            if self.definition.is_swing_high(window):
                swing_high = self._build_swing_high(
                    window=window,
                    candle_index=middle_index,
                    previous_high=previous_high,
                    previous_low=previous_low,
                )
                highs.append(swing_high)
                self.store.upsert(swing_high)
                self._log_swing_detected(swing_high)

            if self.definition.is_swing_low(window):
                swing_low = self._build_swing_low(
                    window=window,
                    candle_index=middle_index,
                    previous_high=previous_high,
                    previous_low=previous_low,
                )
                lows.append(swing_low)
                self.store.upsert(swing_low)
                self._log_swing_detected(swing_low)

        duration_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "Swing detection scan completed",
            extra={
                "swing_highs": len(highs),
                "swing_lows": len(lows),
                "count": len(highs) + len(lows),
                "duration_ms": duration_ms,
            },
        )
        return SwingDetectionResult(
            swing_highs=tuple(highs),
            swing_lows=tuple(lows),
            duration_ms=duration_ms,
        )

    def process_closed_candle(self, candle: Candle) -> tuple[Swing, ...]:
        """Process one newly closed candle without rescanning history."""
        self._validate_closed_candle(candle)
        key = (candle.symbol, candle.timeframe)
        buffer = self._stream_buffers[key]
        buffer.append(candle)
        self._stream_indexes[key] += 1
        logger.debug(
            "Incremental candle processed",
            extra={
                "symbol": candle.symbol,
                "timeframe": candle.timeframe.label,
                "timestamp": candle.timestamp.isoformat(),
                "buffer_size": len(buffer),
            },
        )

        if len(buffer) < self.definition.window_size:
            return ()

        window = tuple(buffer)
        self._validate_consecutive_window(window)
        middle_index = self._stream_indexes[key] - 2
        previous_high = self.get_latest_swing_high(symbol=candle.symbol, timeframe=candle.timeframe)
        previous_low = self.get_latest_swing_low(symbol=candle.symbol, timeframe=candle.timeframe)
        detected: list[Swing] = []

        if self.definition.is_swing_high(window):
            swing_high = self._build_swing_high(
                window=window,
                candle_index=middle_index,
                previous_high=previous_high,
                previous_low=previous_low,
            )
            detected.append(self.store.upsert(swing_high))
            self._log_swing_detected(swing_high)

        if self.definition.is_swing_low(window):
            swing_low = self._build_swing_low(
                window=window,
                candle_index=middle_index,
                previous_high=previous_high,
                previous_low=previous_low,
            )
            detected.append(self.store.upsert(swing_low))
            self._log_swing_detected(swing_low)

        return tuple(detected)

    def get_swing_by_id(self, swing_id: str) -> Swing | None:
        """Return a swing by ID."""
        return self.store.get_swing_by_id(swing_id)

    def get_latest_swing_high(
        self,
        symbol: str,
        timeframe: str | int | Timeframe,
    ) -> SwingHigh | None:
        """Return the latest swing high for a symbol and timeframe."""
        swing = self.store.latest(symbol=symbol, timeframe=timeframe, swing_type=SwingType.HIGH)
        return swing if isinstance(swing, SwingHigh) else None

    def get_latest_swing_low(
        self,
        symbol: str,
        timeframe: str | int | Timeframe,
    ) -> SwingLow | None:
        """Return the latest swing low for a symbol and timeframe."""
        swing = self.store.latest(symbol=symbol, timeframe=timeframe, swing_type=SwingType.LOW)
        return swing if isinstance(swing, SwingLow) else None

    def get_active_swings(
        self,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
    ) -> tuple[Swing, ...]:
        """Return active swings."""
        return self.store.get_active_swings(symbol=symbol, timeframe=timeframe)

    def get_swings_between(
        self,
        symbol: str,
        timeframe: str | int | Timeframe,
        start: datetime,
        end: datetime,
        swing_type: SwingType | None = None,
        status: SwingStatus | None = None,
    ) -> tuple[Swing, ...]:
        """Return swings inside a market-time range."""
        return self.store.get_swings_between(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            swing_type=swing_type,
            status=status,
        )

    def get_swings_for_timeframe(
        self,
        symbol: str,
        timeframe: str | int | Timeframe,
        swing_type: SwingType | None = None,
        status: SwingStatus | None = None,
        limit: int | None = None,
    ) -> tuple[Swing, ...]:
        """Return swings for a symbol and timeframe."""
        return self.store.get_swings_for_timeframe(
            symbol=symbol,
            timeframe=timeframe,
            swing_type=swing_type,
            status=status,
            limit=limit,
        )

    def update_swing_status(
        self,
        swing_id: str,
        status: SwingStatus,
        changed_at: datetime,
        reason: str | None = None,
    ) -> Swing:
        """Update a swing lifecycle state through the authoritative service."""
        existing = self._require_swing(swing_id)
        changed_at_utc = ensure_utc(changed_at)
        metadata = dict(existing.metadata)
        if reason is not None:
            metadata["status_reason"] = reason

        updated = replace(
            existing,
            status=status,
            updated_at=changed_at_utc,
            status_updated_at=changed_at_utc,
            metadata=metadata,
        )
        self.store.replace(updated)
        logger.info(
            "Swing status updated",
            extra={"swing_id": swing_id, "status": status.value, "changed_at": changed_at_utc.isoformat()},
        )
        return updated

    def mark_strategy_candidate(self, swing_id: str, is_candidate: bool = True) -> Swing:
        """Update the strategy candidate flag through the service API."""
        existing = self._require_swing(swing_id)
        updated = replace(existing, is_strategy_candidate=is_candidate)
        self.store.replace(updated)
        logger.info(
            "Strategy candidate flag updated",
            extra={"swing_id": swing_id, "is_strategy_candidate": is_candidate},
        )
        return updated

    def update_strategy_flags(
        self,
        swing_id: str,
        touched_htf_fvg: bool | None = None,
        valid_for_strategy: bool | None = None,
        expansion_confirmed: bool | None = None,
    ) -> Swing:
        """Update strategy validation flags without performing strategy logic."""
        existing = self._require_swing(swing_id)
        updated = replace(
            existing,
            touched_htf_fvg=existing.touched_htf_fvg if touched_htf_fvg is None else touched_htf_fvg,
            valid_for_strategy=existing.valid_for_strategy if valid_for_strategy is None else valid_for_strategy,
            expansion_confirmed=existing.expansion_confirmed if expansion_confirmed is None else expansion_confirmed,
        )
        self.store.replace(updated)
        logger.info("Strategy flags updated", extra={"swing_id": swing_id})
        return updated

    def update_structure_metadata(
        self,
        swing_id: str,
        structure_label: StructureLabel | None = None,
        parent_swing_id: str | None = None,
    ) -> Swing:
        """Update future structure metadata through the service API."""
        existing = self._require_swing(swing_id)
        updated = replace(
            existing,
            structure_label=structure_label,
            parent_swing_id=parent_swing_id,
        )
        self.store.replace(updated)
        logger.info("Structure metadata updated", extra={"swing_id": swing_id})
        return updated

    def _build_swing_high(
        self,
        *,
        window: Sequence[Candle],
        candle_index: int,
        previous_high: Swing | None,
        previous_low: Swing | None,
    ) -> SwingHigh:
        """Build a SwingHigh from a valid three-candle window."""
        source_ids = tuple(candle_id(candle) for candle in window)
        middle = window[1]
        return SwingHigh(
            swing_id=build_swing_id(
                symbol=middle.symbol,
                timeframe=middle.timeframe,
                timestamp=middle.timestamp,
                swing_type=SwingType.HIGH,
                source_candle_ids=source_ids,
            ),
            symbol=middle.symbol,
            timeframe=middle.timeframe,
            timestamp=middle.timestamp,
            candidate_detected_at=middle.timestamp,
            confirmed_at=window[2].end_timestamp,
            price=middle.high,
            candle_index=candle_index,
            left_candle=window[0],
            middle_candle=middle,
            right_candle=window[2],
            source_candle_ids=source_ids,
            status=SwingStatus.ACTIVE,
            strength_score=self.scorer.score(
                swing_type=SwingType.HIGH,
                source_candles=window,
                previous_swing_high=previous_high,
                previous_swing_low=previous_low,
            ),
            previous_swing_high_id=previous_high.swing_id if previous_high else None,
            previous_swing_low_id=previous_low.swing_id if previous_low else None,
        )

    def _build_swing_low(
        self,
        *,
        window: Sequence[Candle],
        candle_index: int,
        previous_high: Swing | None,
        previous_low: Swing | None,
    ) -> SwingLow:
        """Build a SwingLow from a valid three-candle window."""
        source_ids = tuple(candle_id(candle) for candle in window)
        middle = window[1]
        return SwingLow(
            swing_id=build_swing_id(
                symbol=middle.symbol,
                timeframe=middle.timeframe,
                timestamp=middle.timestamp,
                swing_type=SwingType.LOW,
                source_candle_ids=source_ids,
            ),
            symbol=middle.symbol,
            timeframe=middle.timeframe,
            timestamp=middle.timestamp,
            candidate_detected_at=middle.timestamp,
            confirmed_at=window[2].end_timestamp,
            price=middle.low,
            candle_index=candle_index,
            left_candle=window[0],
            middle_candle=middle,
            right_candle=window[2],
            source_candle_ids=source_ids,
            status=SwingStatus.ACTIVE,
            strength_score=self.scorer.score(
                swing_type=SwingType.LOW,
                source_candles=window,
                previous_swing_high=previous_high,
                previous_swing_low=previous_low,
            ),
            previous_swing_high_id=previous_high.swing_id if previous_high else None,
            previous_swing_low_id=previous_low.swing_id if previous_low else None,
        )

    def _prepare_historical_candles(self, candles: Sequence[Candle]) -> tuple[Candle, ...]:
        """Validate and sort historical candles."""
        ordered = tuple(sorted(candles, key=lambda candle: candle.timestamp))
        if not ordered:
            return ()
        first = ordered[0]
        seen_timestamps: set[datetime] = set()
        for candle in ordered:
            self._validate_closed_candle(candle)
            if candle.symbol != first.symbol:
                raise ValueError("historical swing scan requires one symbol")
            if candle.timeframe != first.timeframe:
                raise ValueError("historical swing scan requires one timeframe")
            if candle.timestamp in seen_timestamps:
                raise ValueError("duplicate candle timestamps are invalid")
            seen_timestamps.add(candle.timestamp)
        return ordered

    @staticmethod
    def _validate_closed_candle(candle: Candle) -> None:
        """Validate that the engine only consumes closed candles."""
        if candle.status is not CandleStatus.CLOSED:
            raise ValueError("SwingDetectionEngine only consumes closed candles")

    @staticmethod
    def _validate_consecutive_window(candles: Sequence[Candle]) -> None:
        """Validate strict symbol, timeframe, and timestamp continuity."""
        left, middle, right = candles
        if not (left.symbol == middle.symbol == right.symbol):
            raise ValueError("swing window candles must share one symbol")
        if not (left.timeframe == middle.timeframe == right.timeframe):
            raise ValueError("swing window candles must share one timeframe")
        expected_middle = left.end_timestamp
        expected_right = middle.end_timestamp
        if middle.timestamp != expected_middle or right.timestamp != expected_right:
            raise ValueError("swing window candles must be consecutive")

    def _require_swing(self, swing_id: str) -> Swing:
        """Return an existing swing or raise a clear error."""
        swing = self.store.get_swing_by_id(swing_id)
        if swing is None:
            raise KeyError(f"unknown swing_id: {swing_id}")
        return swing

    @staticmethod
    def _log_swing_detected(swing: Swing) -> None:
        """Emit a structured swing detection log."""
        message = "Swing High detected" if swing.swing_type is SwingType.HIGH else "Swing Low detected"
        logger.info(
            message,
            extra={
                "swing_id": swing.swing_id,
                "symbol": swing.symbol,
                "timeframe": swing.timeframe.label,
                "timestamp": swing.timestamp.isoformat(),
                "confirmed_at": swing.confirmed_at.isoformat(),
                "price": str(swing.price),
                "strength_score": swing.strength_score,
            },
        )


def candle_id(candle: Candle) -> str:
    """Return a deterministic source candle ID for replay compatibility."""
    raw = "|".join(
        (
            candle.symbol,
            candle.timeframe.label,
            candle.timestamp.isoformat(),
            str(candle.open),
            str(candle.high),
            str(candle.low),
            str(candle.close),
            str(candle.volume),
        )
    )
    return f"cndl_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def benchmark_detection(engine: SwingDetectionEngine, candles: Sequence[Candle]) -> dict[str, float]:
    """Run a small benchmark and return validation metrics."""
    started_at = perf_counter()
    result = engine.detect_all_swings(candles)
    elapsed_ms = (perf_counter() - started_at) * 1000
    candles_per_second = (len(candles) / (elapsed_ms / 1000)) if elapsed_ms else 0.0
    return {
        "candles": float(len(candles)),
        "swings": float(result.count),
        "duration_ms": elapsed_ms,
        "candles_per_second": candles_per_second,
    }
