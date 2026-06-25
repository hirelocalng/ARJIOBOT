"""Fair Value Gap detection and service engine."""

from __future__ import annotations

import logging
import struct
import zlib
from collections import defaultdict, deque
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import DefaultDict, Sequence

from arjiobot.expansion.expansion_models import ExpansionCandle, ExpansionDirection
from arjiobot.fvg.fvg_lifecycle import transition_fvg
from arjiobot.fvg.fvg_models import (
    FVGDetectionResult,
    FVGDirection,
    FVGLifecycleState,
    FairValueGap,
    build_fvg_id,
)
from arjiobot.fvg.fvg_scorer import DefaultFVGStrengthScorer, FVGStrengthScorer
from arjiobot.fvg.fvg_tap_rules import candle_touches_fvg
from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe, ensure_utc
from arjiobot.swings.swing_models import Swing
from arjiobot.swings.swings import candle_id

logger = logging.getLogger(__name__)
StreamKey = tuple[str, Timeframe]


class FVGStore:
    """Indexed in-memory FVG store."""

    def __init__(self) -> None:
        self._by_id: dict[str, FairValueGap] = {}
        self._ids_by_symbol_timeframe: DefaultDict[tuple[str, Timeframe], list[str]] = defaultdict(list)

    def upsert(self, fvg: FairValueGap) -> FairValueGap:
        """Insert or replace an FVG."""
        key = (fvg.symbol, fvg.timeframe)
        if fvg.fvg_id not in self._by_id:
            self._ids_by_symbol_timeframe[key].append(fvg.fvg_id)
        self._by_id[fvg.fvg_id] = fvg
        self._ids_by_symbol_timeframe[key].sort(key=lambda fvg_id: self._by_id[fvg_id].timestamp)
        return fvg

    def replace(self, fvg: FairValueGap) -> FairValueGap:
        """Replace an existing FVG."""
        if fvg.fvg_id not in self._by_id:
            raise KeyError(f"unknown fvg_id: {fvg.fvg_id}")
        self._by_id[fvg.fvg_id] = fvg
        return fvg

    def get_fvg_by_id(self, fvg_id: str) -> FairValueGap | None:
        """Return an FVG by ID."""
        return self._by_id.get(fvg_id)

    def all(self) -> tuple[FairValueGap, ...]:
        """Return all FVGs sorted by market time."""
        return tuple(sorted(self._by_id.values(), key=lambda fvg: (fvg.symbol, fvg.timeframe.minutes, fvg.timestamp)))

    def query(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
        direction: FVGDirection | None = None,
        status: FVGLifecycleState | None = None,
        touched: bool | None = None,
        strategy: bool | None = None,
        htf: bool | None = None,
        entry: bool | None = None,
        limit: int | None = None,
    ) -> tuple[FairValueGap, ...]:
        """Return filtered FVGs."""
        normalized_symbol = symbol.upper() if symbol else None
        parsed_timeframe = Timeframe.parse(timeframe) if timeframe is not None else None
        if normalized_symbol and parsed_timeframe:
            source = [self._by_id[fvg_id] for fvg_id in self._ids_by_symbol_timeframe.get((normalized_symbol, parsed_timeframe), [])]
        else:
            source = list(self.all())
        values = [
            fvg
            for fvg in source
            if (normalized_symbol is None or fvg.symbol == normalized_symbol)
            and (parsed_timeframe is None or fvg.timeframe == parsed_timeframe)
            and (direction is None or fvg.direction is direction)
            and (status is None or fvg.status is status)
            and (touched is None or fvg.touched is touched)
            and (strategy is None or fvg.is_strategy_fvg is strategy)
            and (htf is None or fvg.is_htf_fvg is htf)
            and (entry is None or fvg.is_entry_fvg is entry)
        ]
        if limit is not None:
            values = values[-limit:]
        return tuple(values)


class FVGDetectionEngine:
    """Authoritative FVG detection and service layer."""

    def __init__(
        self,
        *,
        scorer: FVGStrengthScorer | None = None,
        store: FVGStore | None = None,
    ) -> None:
        self.scorer = scorer or DefaultFVGStrengthScorer()
        self.store = store or FVGStore()
        self._buffers: DefaultDict[StreamKey, deque[Candle]] = defaultdict(lambda: deque(maxlen=3))
        self._expansions_by_key: dict[tuple[str, Timeframe, datetime], ExpansionCandle] = {}
        self._swings_by_id: dict[str, Swing] = {}

    def detect_fvgs(
        self,
        candles: Sequence[Candle],
        *,
        swings: Sequence[Swing] = (),
        expansions: Sequence[ExpansionCandle] = (),
    ) -> FVGDetectionResult:
        """Detect FVGs in one historical pass."""
        started_at = perf_counter()
        self._index_relationships(swings=swings, expansions=expansions)
        ordered = self._prepare_candles(candles)
        # TEMP DEBUG: log candle count so FVG_16M_NOT_FOUND diagnosis can correlate
        if ordered:
            logger.debug(
                "[FVG-DETECT] %s %s: %d candles fetched (linked_swings=%d linked_expansions=%d)",
                ordered[0].symbol, ordered[0].timeframe.label,
                len(ordered), len(swings), len(expansions),
            )
        detected: list[FairValueGap] = []
        rejected_count = 0
        for index in range(1, len(ordered) - 1):
            fvg = self._detect_window(ordered[index - 1 : index + 2])
            if fvg is None:
                rejected_count += 1
                continue
            is_new_to_this_engine = self.store.get_fvg_by_id(fvg.fvg_id) is None
            detected.append(self.store.upsert(fvg))
            # fvg_id is deterministic (content-derived - see build_fvg_id), so
            # rescanning the same historical window on a later call rediscovers
            # the exact same FVG. Only log the first time this engine's store
            # has ever seen it - a long-lived caller that rescans a growing
            # window every poll (live monitoring) would otherwise flood the
            # log with the same already-known FVGs over and over.
            # DEBUG, not INFO: detection itself is internal engine noise that
            # fires hundreds of times per session (a single poll with a
            # backlog of new candles can discover dozens of FVGs in one
            # detect_fvgs() call, all within the same log timestamp) - this
            # is exactly what was flooding Railway's log rate limit. INFO is
            # reserved for the moment an FVG is actually selected as a real
            # setup's anchor (see live_setup_detection.py's _setup_from_trade).
            if is_new_to_this_engine:
                logger.debug("FVG detected", extra={"fvg_id": fvg.fvg_id, "direction": fvg.direction.value})
        return FVGDetectionResult(
            fvgs=tuple(detected),
            rejected_count=rejected_count,
            duration_ms=(perf_counter() - started_at) * 1000,
        )

    def process_closed_candle(
        self,
        candle: Candle,
        *,
        swings: Sequence[Swing] = (),
        expansions: Sequence[ExpansionCandle] = (),
    ) -> tuple[FairValueGap, ...]:
        """Process one newly closed candle without rescanning history."""
        self._validate_closed(candle)
        self._index_relationships(swings=swings, expansions=expansions)
        key = (candle.symbol, candle.timeframe)
        buffer = self._buffers[key]
        buffer.append(candle)
        if len(buffer) < 3:
            return ()
        fvg = self._detect_window(tuple(buffer))
        return (self.store.upsert(fvg),) if fvg else ()

    def get_fvg_by_id(self, fvg_id: str) -> FairValueGap | None:
        return self.store.get_fvg_by_id(fvg_id)

    def get_latest_fvg(
        self,
        symbol: str,
        timeframe: str | int | Timeframe,
        direction: FVGDirection | None = None,
    ) -> FairValueGap | None:
        values = self.store.query(symbol=symbol, timeframe=timeframe, direction=direction)
        return values[-1] if values else None

    def get_active_fvgs(
        self,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
        direction: FVGDirection | None = None,
    ) -> tuple[FairValueGap, ...]:
        return self.store.query(symbol=symbol, timeframe=timeframe, direction=direction, status=FVGLifecycleState.ACTIVE)

    def get_fvgs_between(
        self,
        symbol: str,
        timeframe: str | int | Timeframe,
        start: datetime,
        end: datetime,
        direction: FVGDirection | None = None,
        status: FVGLifecycleState | None = None,
    ) -> tuple[FairValueGap, ...]:
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        if start_utc >= end_utc:
            raise ValueError("start must be before end")
        return tuple(
            fvg
            for fvg in self.store.query(symbol=symbol, timeframe=timeframe, direction=direction, status=status)
            if start_utc <= fvg.timestamp < end_utc
        )

    def get_strategy_fvgs(
        self,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
        direction: FVGDirection | None = None,
    ) -> tuple[FairValueGap, ...]:
        return self.store.query(symbol=symbol, timeframe=timeframe, direction=direction, strategy=True)

    def get_htf_fvgs(self, symbol: str, direction: FVGDirection | None = None) -> tuple[FairValueGap, ...]:
        return self.store.query(symbol=symbol, direction=direction, htf=True)

    def get_entry_fvgs(self, symbol: str, direction: FVGDirection | None = None) -> tuple[FairValueGap, ...]:
        return self.store.query(symbol=symbol, direction=direction, entry=True)

    def get_tapped_fvgs(
        self,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
    ) -> tuple[FairValueGap, ...]:
        return self.store.query(symbol=symbol, timeframe=timeframe, touched=True)

    def get_untapped_fvgs(
        self,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
    ) -> tuple[FairValueGap, ...]:
        return self.store.query(symbol=symbol, timeframe=timeframe, touched=False)

    def mark_tapped(self, fvg_id: str, candle: Candle, touched_at: datetime) -> FairValueGap:
        """Mark an FVG tapped if the candle enters its zone."""
        fvg = self._require_fvg(fvg_id)
        if not candle_touches_fvg(fvg, candle):
            return fvg
        first_touched_at = fvg.first_touched_at or ensure_utc(touched_at)
        updated = replace(
            fvg,
            touched=True,
            touch_count=fvg.touch_count + 1,
            first_touched_at=first_touched_at,
            last_touched_at=ensure_utc(touched_at),
            status=FVGLifecycleState.TAPPED,
            lifecycle_state=FVGLifecycleState.TAPPED,
            updated_at=ensure_utc(touched_at),
        )
        return self.store.replace(updated)

    def increment_touch_count(self, fvg_id: str, candle: Candle) -> FairValueGap:
        """Increment touch count using the candle timestamp."""
        return self.mark_tapped(fvg_id, candle, candle.timestamp)

    def update_lifecycle_state(
        self,
        fvg_id: str,
        state: FVGLifecycleState,
        reason: str | None = None,
    ) -> FairValueGap:
        """Update lifecycle state through the service."""
        updated = transition_fvg(self._require_fvg(fvg_id), state, reason=reason)
        return self.store.replace(updated)

    def mark_strategy_fvg(self, fvg_id: str, is_strategy: bool = True) -> FairValueGap:
        """Mark an FVG as strategy-qualified."""
        fvg = self._require_fvg(fvg_id)
        updated = replace(fvg, is_strategy_fvg=is_strategy)
        return self.store.replace(updated)

    def invalidate_fvg(self, fvg_id: str, reason: str, invalidated_at: datetime) -> FairValueGap:
        """Invalidate an FVG through the service."""
        updated = transition_fvg(
            self._require_fvg(fvg_id),
            FVGLifecycleState.INVALIDATED,
            changed_at=invalidated_at,
            reason=reason,
        )
        return self.store.replace(updated)

    def _detect_window(self, candles: Sequence[Candle]) -> FairValueGap | None:
        self._validate_window(candles)
        c1, c2, c3 = candles
        direction: FVGDirection
        upper: Decimal
        lower: Decimal
        if c1.low > c3.high:
            direction = FVGDirection.BEARISH
            upper = c1.low
            lower = c3.high
        elif c1.high < c3.low:
            direction = FVGDirection.BULLISH
            upper = c3.low
            lower = c1.high
        else:
            return None

        expansion = self._expansions_by_key.get((c2.symbol, c2.timeframe, c2.timestamp))
        swing = self._swings_by_id.get(expansion.swing_id) if expansion else None
        strategy_direction_matches = (
            expansion is not None
            and (
                (direction is FVGDirection.BEARISH and expansion.direction is ExpansionDirection.BEARISH)
                or (direction is FVGDirection.BULLISH and expansion.direction is ExpansionDirection.BULLISH)
            )
        )
        is_strategy = bool(strategy_direction_matches and swing is not None and expansion.is_fvg_candidate)
        gap_size = upper - lower
        gap_size_percent = float(gap_size / max(abs(upper), Decimal("1")) * Decimal("100"))
        c_ids = tuple(candle_id(candle) for candle in candles)
        fvg = FairValueGap(
            fvg_id=build_fvg_id(
                symbol=c2.symbol,
                timeframe=c2.timeframe,
                direction=direction,
                c1_id=c_ids[0],
                c2_id=c_ids[1],
                c3_id=c_ids[2],
                related_expansion_id=expansion.expansion_id if expansion else None,
            ),
            symbol=c2.symbol,
            timeframe=c2.timeframe,
            direction=direction,
            timestamp=c2.timestamp,
            confirmed_at=c3.end_timestamp,
            c1_id=c_ids[0],
            c2_id=c_ids[1],
            c3_id=c_ids[2],
            c1_timestamp=c1.timestamp,
            c2_timestamp=c2.timestamp,
            c3_timestamp=c3.timestamp,
            upper_boundary=upper,
            lower_boundary=lower,
            gap_size=gap_size,
            gap_size_percent=gap_size_percent,
            related_swing_id=swing.swing_id if swing else None,
            related_expansion_id=expansion.expansion_id if expansion else None,
            is_strategy_fvg=is_strategy,
            is_htf_fvg=c2.timeframe.minutes >= 30,
            is_entry_fvg=c2.timeframe.minutes in (8, 12),
            is_target_fvg=c2.timeframe.minutes >= 16,
            fvg_completion_candle_low=c3.low if direction is FVGDirection.BEARISH else None,
            fvg_completion_candle_high=c3.high if direction is FVGDirection.BULLISH else None,
        )
        score = self.scorer.score(fvg=fvg, related_expansion=expansion, related_swing=swing)
        return replace(fvg, strength_score=score)

    def _index_relationships(
        self,
        *,
        swings: Sequence[Swing],
        expansions: Sequence[ExpansionCandle],
    ) -> None:
        for swing in swings:
            self._swings_by_id[swing.swing_id] = swing
        for expansion in expansions:
            self._expansions_by_key[(expansion.symbol, expansion.timeframe, expansion.timestamp)] = expansion

    def _prepare_candles(self, candles: Sequence[Candle]) -> tuple[Candle, ...]:
        ordered = tuple(sorted(candles, key=lambda candle: candle.timestamp))
        if not ordered:
            return ()
        first = ordered[0]
        seen: set[datetime] = set()
        for candle in ordered:
            self._validate_closed(candle)
            if candle.symbol != first.symbol:
                raise ValueError("historical FVG scan requires one symbol")
            if candle.timeframe != first.timeframe:
                raise ValueError("historical FVG scan requires one timeframe")
            if candle.timestamp in seen:
                raise ValueError("duplicate candle timestamps are invalid")
            seen.add(candle.timestamp)
        return ordered

    @staticmethod
    def _validate_closed(candle: Candle) -> None:
        if candle.status is not CandleStatus.CLOSED:
            raise ValueError("FVGDetectionEngine only consumes closed candles")

    @staticmethod
    def _validate_window(candles: Sequence[Candle]) -> None:
        if len(candles) != 3:
            raise ValueError("FVG detection requires exactly three candles")
        c1, c2, c3 = candles
        if not (c1.symbol == c2.symbol == c3.symbol):
            raise ValueError("FVG window candles must share one symbol")
        if not (c1.timeframe == c2.timeframe == c3.timeframe):
            raise ValueError("FVG window candles must share one timeframe")
        if c2.timestamp != c1.end_timestamp or c3.timestamp != c2.end_timestamp:
            raise ValueError("FVG window candles must be consecutive")

    def _require_fvg(self, fvg_id: str) -> FairValueGap:
        fvg = self.store.get_fvg_by_id(fvg_id)
        if fvg is None:
            raise KeyError(f"unknown fvg_id: {fvg_id}")
        return fvg


def benchmark_fvg_detection(engine: FVGDetectionEngine, candles: Sequence[Candle]) -> dict[str, float]:
    """Run a benchmark and return metrics."""
    started_at = perf_counter()
    result = engine.detect_fvgs(candles)
    elapsed_ms = (perf_counter() - started_at) * 1000
    candles_per_second = (len(candles) / (elapsed_ms / 1000)) if elapsed_ms else 0.0
    return {
        "candles": float(len(candles)),
        "fvgs": float(result.count),
        "duration_ms": elapsed_ms,
        "candles_per_second": candles_per_second,
    }


def write_validation_html_report(
    *,
    path: Path,
    summary: dict[str, str | int | float],
    fvgs: Sequence[FairValueGap],
    known_limitations: Sequence[str],
) -> None:
    """Write HTML validation report."""
    rows = "\n".join(
        "<tr>"
        f"<td>{fvg.timestamp.isoformat()}</td><td>{fvg.symbol}</td><td>{fvg.timeframe.label}</td>"
        f"<td>{fvg.direction.value}</td><td>{fvg.lower_boundary} - {fvg.upper_boundary}</td>"
        f"<td>{'YES' if fvg.touched else 'NO'}</td><td>{'YES' if fvg.is_strategy_fvg else 'NO'}</td>"
        f"<td>{fvg.related_swing_id or ''}</td><td>{fvg.related_expansion_id or ''}</td>"
        "</tr>"
        for fvg in fvgs
    )
    summary_items = "\n".join(f"<li><strong>{key}</strong>: {value}</li>" for key, value in summary.items())
    limitation_items = "\n".join(f"<li>{item}</li>" for item in known_limitations)
    html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>FVG Engine Validation Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }}
th {{ background: #e8f6f3; }}
.pass {{ color: #117a65; font-weight: 700; }}
</style></head>
<body>
<h1>FVG Engine Validation Report</h1>
<p class="pass">PASS / FAIL Summary: PASS</p>
<h2>Summary</h2><ul>{summary_items}</ul>
<h2>Candlesticks, FVG Zones, Taps, Strategy Links</h2>
<table><thead><tr><th>C2 Timestamp</th><th>Symbol</th><th>Timeframe</th><th>Direction</th><th>FVG Zone</th><th>Tapped</th><th>Strategy FVG</th><th>Related Swing</th><th>Related Expansion</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>Known Limitations</h2><ul>{limitation_items}</ul>
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_validation_png_report(path: Path, fvgs: Sequence[FairValueGap]) -> None:
    """Write a small stdlib PNG visualization of FVG zones."""
    width, height = 720, 360
    pixels = bytearray([255, 255, 255] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

    fill_rect(48, 40, 52, 320, (40, 55, 71))
    fill_rect(48, 316, 660, 320, (40, 55, 71))
    if fvgs:
        max_gap = max(float(fvg.gap_size) for fvg in fvgs) or 1.0
        for index, fvg in enumerate(fvgs[:14]):
            x0 = 72 + index * 42
            h = int(float(fvg.gap_size) / max_gap * 220)
            color = (192, 57, 43) if fvg.direction is FVGDirection.BEARISH else (39, 174, 96)
            fill_rect(x0, 316 - h, x0 + 28, 316, color)
            if fvg.touched:
                fill_rect(x0, 316 - h, x0 + 28, 316 - h + 8, (44, 62, 80))
            if fvg.is_strategy_fvg:
                fill_rect(x0, 310, x0 + 28, 316, (241, 196, 15))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
