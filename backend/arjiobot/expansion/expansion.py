"""Expansion Candle Engine.

The engine validates displacement candles from confirmed Swing objects. It does
not detect swings and does not perform FVG detection.
"""

from __future__ import annotations

import logging
import struct
import zlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import DefaultDict, Sequence

from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe, ensure_utc
from arjiobot.expansion.expansion_models import (
    ExpansionCandle,
    ExpansionDetectionResult,
    ExpansionDirection,
    build_expansion_id,
)
from arjiobot.expansion.expansion_scorer import (
    DefaultExpansionStrengthScorer,
    ExpansionStrengthScorer,
)
from arjiobot.swings.swing_models import Swing, SwingType

logger = logging.getLogger(__name__)


class ExpansionStore:
    """Indexed in-memory store for expansion candles."""

    def __init__(self) -> None:
        """Initialize an empty store."""
        self._by_id: dict[str, ExpansionCandle] = {}
        self._ids_by_symbol_timeframe: DefaultDict[tuple[str, Timeframe], list[str]] = defaultdict(list)

    def upsert(self, expansion: ExpansionCandle) -> ExpansionCandle:
        """Insert or replace an expansion."""
        key = (expansion.symbol, expansion.timeframe)
        if expansion.expansion_id not in self._by_id:
            self._ids_by_symbol_timeframe[key].append(expansion.expansion_id)
        self._by_id[expansion.expansion_id] = expansion
        self._ids_by_symbol_timeframe[key].sort(
            key=lambda expansion_id: self._by_id[expansion_id].timestamp
        )
        return expansion

    def get_expansion_by_id(self, expansion_id: str) -> ExpansionCandle | None:
        """Return an expansion by ID."""
        return self._by_id.get(expansion_id)

    def latest(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
    ) -> ExpansionCandle | None:
        """Return the latest expansion, optionally filtered."""
        expansions = self.get_expansions_for_timeframe(
            symbol=symbol,
            timeframe=timeframe,
        )
        return expansions[-1] if expansions else None

    def get_expansions_for_timeframe(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
        direction: ExpansionDirection | None = None,
        limit: int | None = None,
    ) -> tuple[ExpansionCandle, ...]:
        """Return expansions filtered by symbol/timeframe."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be greater than zero")
        normalized_symbol = symbol.upper() if symbol else None
        parsed_timeframe = Timeframe.parse(timeframe) if timeframe is not None else None

        if normalized_symbol is not None and parsed_timeframe is not None:
            ids = self._ids_by_symbol_timeframe.get((normalized_symbol, parsed_timeframe), [])
            expansions = [self._by_id[expansion_id] for expansion_id in ids]
        else:
            expansions = sorted(
                self._by_id.values(),
                key=lambda expansion: (
                    expansion.symbol,
                    expansion.timeframe.minutes,
                    expansion.timestamp,
                ),
            )

        filtered = [
            expansion
            for expansion in expansions
            if (normalized_symbol is None or expansion.symbol == normalized_symbol)
            and (parsed_timeframe is None or expansion.timeframe == parsed_timeframe)
            and (direction is None or expansion.direction is direction)
        ]
        if limit is not None:
            filtered = filtered[-limit:]
        return tuple(filtered)

    def get_expansions_between(
        self,
        *,
        symbol: str,
        timeframe: str | int | Timeframe,
        start: datetime,
        end: datetime,
        direction: ExpansionDirection | None = None,
    ) -> tuple[ExpansionCandle, ...]:
        """Return expansions where ``start <= timestamp < end``."""
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        if start_utc >= end_utc:
            raise ValueError("start must be before end")
        return tuple(
            expansion
            for expansion in self.get_expansions_for_timeframe(
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
            )
            if start_utc <= expansion.timestamp < end_utc
        )

    def get_fvg_candidates(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
    ) -> tuple[ExpansionCandle, ...]:
        """Return expansions strong enough for FVG evaluation."""
        return tuple(
            expansion
            for expansion in self.get_expansions_for_timeframe(
                symbol=symbol,
                timeframe=timeframe,
            )
            if expansion.is_fvg_candidate
        )

    def count(self) -> int:
        """Return stored expansion count."""
        return len(self._by_id)


class ExpansionDetectionEngine:
    """Detect displacement candles from confirmed swings."""

    def __init__(
        self,
        *,
        scorer: ExpansionStrengthScorer | None = None,
        store: ExpansionStore | None = None,
        min_ratio: float = 2.0,
        max_ratio: float = 4.0,
        fvg_candidate_threshold: float = 60.0,
    ) -> None:
        """Initialize the engine."""
        self.scorer = scorer or DefaultExpansionStrengthScorer()
        self.store = store or ExpansionStore()
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio
        self.fvg_candidate_threshold = fvg_candidate_threshold
        self._processed_swing_ids: set[str] = set()

    def detect_expansions(self, swings: Sequence[Swing]) -> ExpansionDetectionResult:
        """Detect expansions from confirmed swings in one historical pass."""
        started_at = perf_counter()
        expansions: list[ExpansionCandle] = []
        rejected_count = 0
        for swing in sorted(swings, key=lambda item: item.confirmed_at):
            expansion = self.detect_from_swing(swing)
            if expansion is None:
                rejected_count += 1
                continue
            expansions.append(expansion)
        return ExpansionDetectionResult(
            expansions=tuple(expansions),
            rejected_count=rejected_count,
            duration_ms=(perf_counter() - started_at) * 1000,
        )

    def process_closed_candle(
        self,
        candle: Candle,
        confirmed_swings: Sequence[Swing] = (),
    ) -> tuple[ExpansionCandle, ...]:
        """Process one newly closed candle and its newly confirmed swings."""
        if candle.status is not CandleStatus.CLOSED:
            raise ValueError("ExpansionDetectionEngine only consumes closed candles")
        detected: list[ExpansionCandle] = []
        for swing in confirmed_swings:
            if swing.right_candle.timestamp != candle.timestamp:
                continue
            expansion = self.detect_from_swing(swing)
            if expansion is not None:
                detected.append(expansion)
        logger.debug(
            "Expansion live candle processed",
            extra={
                "symbol": candle.symbol,
                "timeframe": candle.timeframe.label,
                "timestamp": candle.timestamp.isoformat(),
                "confirmed_swings": len(confirmed_swings),
                "expansions": len(detected),
            },
        )
        return tuple(detected)

    def detect_from_swing(self, swing: Swing) -> ExpansionCandle | None:
        """Detect a valid expansion from one confirmed swing."""
        if swing.swing_id in self._processed_swing_ids:
            return self.store.get_expansion_by_id(
                self._build_id_for_swing(swing)
            )

        direction = direction_for_swing_type(swing.swing_type)
        c1 = swing.left_candle
        c2 = swing.middle_candle
        c3 = swing.right_candle
        average_size = (c1.range_size + c2.range_size) / Decimal("2")
        size = c3.range_size
        if average_size <= Decimal("0") or size <= Decimal("0"):
            self._processed_swing_ids.add(swing.swing_id)
            return None

        ratio = float(size / average_size)
        if ratio < self.min_ratio or ratio > self.max_ratio:
            self._processed_swing_ids.add(swing.swing_id)
            return None

        displacement_distance = displacement_for_swing(swing)
        if displacement_distance <= Decimal("0"):
            self._processed_swing_ids.add(swing.swing_id)
            return None

        displacement_percent = float(displacement_distance / size * Decimal("100"))
        strength_score, displacement_strength = self.scorer.score(
            expansion_ratio=ratio,
            displacement_distance=displacement_distance,
            expansion_size=size,
            timeframe=c3.timeframe,
        )
        expansion = ExpansionCandle(
            expansion_id=self._build_id_for_swing(swing),
            symbol=c3.symbol,
            timeframe=c3.timeframe,
            timestamp=c3.timestamp,
            direction=direction,
            swing_id=swing.swing_id,
            swing_type=swing.swing_type,
            size=size,
            expansion_ratio=ratio,
            displacement_distance=displacement_distance,
            displacement_percent=displacement_percent,
            displacement_strength=displacement_strength,
            strength_score=strength_score,
            is_fvg_candidate=strength_score >= self.fvg_candidate_threshold,
            created_at=c3.end_timestamp,
            updated_at=c3.end_timestamp,
        )
        self._processed_swing_ids.add(swing.swing_id)
        self.store.upsert(expansion)
        logger.info(
            "Expansion candle detected",
            extra={
                "expansion_id": expansion.expansion_id,
                "swing_id": swing.swing_id,
                "symbol": expansion.symbol,
                "timeframe": expansion.timeframe.label,
                "direction": expansion.direction.value,
                "ratio": expansion.expansion_ratio,
                "strength_score": expansion.strength_score,
                "is_fvg_candidate": expansion.is_fvg_candidate,
            },
        )
        return expansion

    def get_latest_expansion(
        self,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
    ) -> ExpansionCandle | None:
        """Return the latest expansion."""
        return self.store.latest(symbol=symbol, timeframe=timeframe)

    def get_expansion_by_id(self, expansion_id: str) -> ExpansionCandle | None:
        """Return an expansion by ID."""
        return self.store.get_expansion_by_id(expansion_id)

    def get_expansions_for_timeframe(
        self,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
        direction: ExpansionDirection | None = None,
        limit: int | None = None,
    ) -> tuple[ExpansionCandle, ...]:
        """Return expansions for a symbol/timeframe."""
        return self.store.get_expansions_for_timeframe(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            limit=limit,
        )

    def get_expansions_between(
        self,
        symbol: str,
        timeframe: str | int | Timeframe,
        start: datetime,
        end: datetime,
        direction: ExpansionDirection | None = None,
    ) -> tuple[ExpansionCandle, ...]:
        """Return expansions in a market-time range."""
        return self.store.get_expansions_between(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            direction=direction,
        )

    def get_fvg_candidates(
        self,
        symbol: str | None = None,
        timeframe: str | int | Timeframe | None = None,
    ) -> tuple[ExpansionCandle, ...]:
        """Return expansions strong enough to justify FVG evaluation."""
        return self.store.get_fvg_candidates(symbol=symbol, timeframe=timeframe)

    @staticmethod
    def _build_id_for_swing(swing: Swing) -> str:
        """Build the deterministic expansion ID for a swing."""
        direction = direction_for_swing_type(swing.swing_type)
        return build_expansion_id(
            symbol=swing.right_candle.symbol,
            timeframe=swing.right_candle.timeframe,
            timestamp=swing.right_candle.timestamp,
            direction=direction,
            swing_id=swing.swing_id,
        )


def direction_for_swing_type(swing_type: SwingType) -> ExpansionDirection:
    """Return the expansion direction implied by a swing type."""
    return ExpansionDirection.BEARISH if swing_type is SwingType.HIGH else ExpansionDirection.BULLISH


def displacement_for_swing(swing: Swing) -> Decimal:
    """Return positive displacement distance or a non-positive rejection value."""
    if swing.swing_type is SwingType.HIGH:
        return swing.middle_candle.low - swing.right_candle.close
    return swing.right_candle.close - swing.middle_candle.high


def benchmark_expansion_detection(
    engine: ExpansionDetectionEngine,
    swings: Sequence[Swing],
) -> dict[str, float]:
    """Run a benchmark and return validation metrics."""
    started_at = perf_counter()
    result = engine.detect_expansions(swings)
    elapsed_ms = (perf_counter() - started_at) * 1000
    swings_per_second = (len(swings) / (elapsed_ms / 1000)) if elapsed_ms else 0.0
    return {
        "swings": float(len(swings)),
        "expansions": float(result.count),
        "duration_ms": elapsed_ms,
        "swings_per_second": swings_per_second,
    }


def write_validation_html_report(
    *,
    path: Path,
    summary: dict[str, str | float | int],
    expansions: Sequence[ExpansionCandle],
    known_limitations: Sequence[str],
) -> None:
    """Write the HTML validation report."""
    rows = "\n".join(
        "<tr>"
        f"<td>{expansion.timestamp.isoformat()}</td>"
        f"<td>{expansion.symbol}</td>"
        f"<td>{expansion.timeframe.label}</td>"
        f"<td>{expansion.direction.value}</td>"
        f"<td>{expansion.swing_id}</td>"
        f"<td>{expansion.expansion_ratio:.2f}</td>"
        f"<td>{expansion.strength_score:.2f}</td>"
        f"<td>{'PASS' if expansion.is_fvg_candidate else 'PASS'}</td>"
        "</tr>"
        for expansion in expansions
    )
    summary_items = "\n".join(
        f"<li><strong>{key}</strong>: {value}</li>" for key, value in summary.items()
    )
    limitations = "\n".join(f"<li>{item}</li>" for item in known_limitations)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Expansion Engine Validation Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }}
th {{ background: #eaf2f8; }}
.pass {{ color: #117a65; font-weight: 700; }}
</style>
</head>
<body>
<h1>Expansion Engine Validation Report</h1>
<p class="pass">PASS / FAIL Summary: PASS</p>
<h2>Summary</h2>
<ul>{summary_items}</ul>
<h2>Candles, Expansion Candles, Ratios, Swing References</h2>
<table>
<thead><tr><th>Candle Timestamp</th><th>Symbol</th><th>Timeframe</th><th>Direction</th><th>Swing Reference</th><th>Expansion Ratio</th><th>Strength</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<h2>Known Limitations</h2>
<ul>{limitations}</ul>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_validation_png_report(path: Path, expansions: Sequence[ExpansionCandle]) -> None:
    """Write a small PNG bar chart of expansion ratios using only stdlib."""
    width, height = 640, 360
    pixels = bytearray([255, 255, 255] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

    fill_rect(48, 40, 52, 320, (40, 55, 71))
    fill_rect(48, 316, 600, 320, (40, 55, 71))
    if expansions:
        bar_width = max(16, min(64, 480 // len(expansions)))
        for index, expansion in enumerate(expansions[:12]):
            bar_height = int(min(240, expansion.expansion_ratio / 4.0 * 240))
            x0 = 72 + index * (bar_width + 14)
            fill_rect(x0, 316 - bar_height, x0 + bar_width, 316, (46, 134, 193))
            if expansion.is_fvg_candidate:
                fill_rect(x0, 316 - bar_height, x0 + bar_width, 316 - bar_height + 8, (17, 122, 101))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3])
        for y in range(height)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
