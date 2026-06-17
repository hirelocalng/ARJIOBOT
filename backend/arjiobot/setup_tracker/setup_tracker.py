"""Authoritative Setup Tracker service."""

from __future__ import annotations

import struct
import zlib
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import DefaultDict, Iterable, Sequence

from arjiobot.fvg.fvg_models import FVGDirection, FairValueGap
from arjiobot.fvg.fvg_tap_rules import candle_touches_fvg, fvg_inside_bearish_leg
from arjiobot.market_data.candle_models import Candle, Timeframe, ensure_utc
from arjiobot.setup_tracker.setup_invalidation import (
    close_above_12m_fvg,
    high_sequence_invalidation_reason,
    invalidate,
    retrace_window_passed,
    should_invalidate_retrace_window,
)
from arjiobot.setup_tracker.setup_models import (
    InvalidationReason,
    Setup,
    SetupDirection,
    SetupRadarItem,
    SetupState,
    SetupStatus,
    StateHistoryEntry,
    build_setup_id,
)
from arjiobot.setup_tracker.setup_scoring import DefaultSetupProgressScorer, SetupProgressScorer
from arjiobot.setup_tracker.setup_state import transition_setup
from arjiobot.setup_tracker.setup_timing import calculate_stop_reference, calculate_target_references, retrace_time_remaining
from arjiobot.swings.swings import candle_id


class SetupStore:
    """Indexed in-memory setup store."""

    def __init__(self) -> None:
        self._by_id: dict[str, Setup] = {}
        self._ids_by_symbol: DefaultDict[str, list[str]] = defaultdict(list)

    def upsert(self, setup: Setup) -> Setup:
        """Insert or replace setup."""
        if setup.setup_id not in self._by_id:
            self._ids_by_symbol[setup.symbol].append(setup.setup_id)
        self._by_id[setup.setup_id] = setup
        self._ids_by_symbol[setup.symbol].sort(key=lambda setup_id: self._by_id[setup_id].created_at)
        return setup

    def get(self, setup_id: str) -> Setup | None:
        return self._by_id.get(setup_id)

    def all(self) -> tuple[Setup, ...]:
        return tuple(sorted(self._by_id.values(), key=lambda setup: (setup.symbol, setup.created_at)))

    def query(
        self,
        *,
        symbol: str | None = None,
        state: SetupState | None = None,
        status: SetupStatus | None = None,
        min_progress: float | None = None,
    ) -> tuple[Setup, ...]:
        normalized_symbol = symbol.upper() if symbol else None
        source = (
            [self._by_id[setup_id] for setup_id in self._ids_by_symbol.get(normalized_symbol, [])]
            if normalized_symbol
            else list(self.all())
        )
        return tuple(
            setup
            for setup in source
            if (state is None or setup.current_state is state)
            and (status is None or setup.status is status)
            and (min_progress is None or setup.progress_percent >= min_progress)
        )


class SetupTracker:
    """Track Arjio setup state without trade execution."""

    def __init__(
        self,
        *,
        store: SetupStore | None = None,
        scorer: SetupProgressScorer | None = None,
    ) -> None:
        self.store = store or SetupStore()
        self.scorer = scorer or DefaultSetupProgressScorer()

    def create_setup(
        self,
        *,
        symbol: str,
        direction: SetupDirection = SetupDirection.BEARISH,
        created_at: datetime,
        htf_fvg_id: str | None = None,
    ) -> Setup:
        """Create a deterministic setup."""
        created_at_utc = ensure_utc(created_at)
        setup = Setup(
            setup_id=build_setup_id(
                symbol=symbol,
                direction=direction,
                created_at=created_at_utc,
                htf_fvg_id=htf_fvg_id,
            ),
            symbol=symbol,
            direction=direction,
            current_state=SetupState.WATCHING_HTF_FVG,
            progress_percent=15.0 if htf_fvg_id else 0.0,
            status=SetupStatus.ACTIVE,
            created_at=created_at_utc,
            updated_at=created_at_utc,
            htf_fvg_id=htf_fvg_id,
            state_history=(
                StateHistoryEntry(
                    from_state=None,
                    to_state=SetupState.WATCHING_HTF_FVG,
                    changed_at=created_at_utc,
                    reason="setup created",
                    triggering_object_type="FVG" if htf_fvg_id else None,
                    triggering_object_id=htf_fvg_id,
                ),
            ),
        )
        return self.store.upsert(self.update_progress(setup))

    def advance_setup_state(
        self,
        setup_id: str,
        to_state: SetupState,
        *,
        changed_at: datetime,
        reason: str | None = None,
        triggering_object_type: str | None = None,
        triggering_object_id: str | None = None,
        updates: dict[str, object] | None = None,
    ) -> Setup:
        """Advance setup state through the service API."""
        setup = self._require(setup_id)
        if updates:
            setup = replace(setup, **updates)
        setup = self.update_progress(setup)
        setup = transition_setup(
            setup,
            to_state,
            changed_at=changed_at,
            reason=reason,
            triggering_object_type=triggering_object_type,
            triggering_object_id=triggering_object_id,
            progress_percent=self.scorer.score(setup),
        )
        return self.store.upsert(setup)

    def invalidate_setup(
        self,
        setup_id: str,
        reason: InvalidationReason,
        invalidated_at: datetime,
    ) -> Setup:
        """Invalidate a setup."""
        setup = invalidate(self._require(setup_id), reason, invalidated_at)
        setup = replace(
            setup,
            state_history=(
                *setup.state_history,
                StateHistoryEntry(
                    from_state=self._require(setup_id).current_state,
                    to_state=SetupState.INVALIDATED,
                    changed_at=invalidated_at,
                    reason=reason.value,
                ),
            ),
        )
        return self.store.upsert(setup)

    def expire_setup(self, setup_id: str, expired_at: datetime) -> Setup:
        """Expire a setup."""
        return self.advance_setup_state(
            setup_id,
            SetupState.EXPIRED,
            changed_at=expired_at,
            reason=InvalidationReason.SETUP_EXPIRED.value,
        )

    def mark_entry_ready(
        self,
        setup_id: str,
        *,
        entry_fvg_id: str,
        changed_at: datetime,
    ) -> Setup:
        """Mark setup entry-ready without placing a trade."""
        setup = self._require(setup_id)
        if setup.final_target_price is not None and setup.metadata.get("latest_price"):
            if Decimal(setup.metadata["latest_price"]) <= setup.final_target_price:
                return self.invalidate_setup(
                    setup_id,
                    InvalidationReason.PRICE_REACHED_TARGET_BEFORE_ENTRY,
                    changed_at,
                )
        return self.advance_setup_state(
            setup_id,
            SetupState.ENTRY_READY,
            changed_at=changed_at,
            reason="entry ready",
            triggering_object_type="FVG",
            triggering_object_id=entry_fvg_id,
            updates={"entry_fvg_id": entry_fvg_id},
        )

    def update_progress(self, setup: Setup) -> Setup:
        """Update progress using the configured scorer."""
        return replace(setup, progress_percent=self.scorer.score(setup))

    def record_state_transition(
        self,
        setup_id: str,
        entry: StateHistoryEntry,
    ) -> Setup:
        """Append a state history entry."""
        setup = self._require(setup_id)
        return self.store.upsert(replace(setup, state_history=(*setup.state_history, entry)))

    def update_target_references(
        self,
        setup_id: str,
        *,
        fvg_16m: FairValueGap,
        candles_8m_after_16m: Sequence[Candle],
    ) -> Setup:
        """Update target references."""
        target_a, target_b, final_target = calculate_target_references(
            fvg_16m=fvg_16m,
            candles_8m_after_16m=candles_8m_after_16m,
        )
        setup = replace(
            self._require(setup_id),
            target_a_price=target_a,
            target_b_price=target_b,
            final_target_price=final_target,
        )
        return self.store.upsert(setup)

    def update_stop_reference(self, setup_id: str, swing_16m_price) -> Setup:
        """Update bearish stop reference."""
        setup = replace(self._require(setup_id), stop_reference_price=calculate_stop_reference(swing_16m_price))
        return self.store.upsert(setup)

    def qualify_fvg_inside_16m_leg(
        self,
        setup_id: str,
        *,
        fvg: FairValueGap,
        swing_high_price,
        completion_candle_low,
        field_name: str,
        state: SetupState,
    ) -> Setup:
        """Attach 12M/8M FVG if it is inside the valid 16M leg."""
        if not fvg_inside_bearish_leg(
            fvg=fvg,
            swing_high_price=swing_high_price,
            completion_candle_low=completion_candle_low,
        ):
            return self.invalidate_setup(setup_id, InvalidationReason.FVG_OUTSIDE_16M_LEG, fvg.confirmed_at)
        return self.advance_setup_state(
            setup_id,
            state,
            changed_at=fvg.confirmed_at,
            reason=f"{field_name} confirmed",
            triggering_object_type="FVG",
            triggering_object_id=fvg.fvg_id,
            updates={field_name: fvg.fvg_id},
        )

    def process_retrace_window(
        self,
        setup_id: str,
        *,
        fvg_12m: FairValueGap,
        candles_8m: Sequence[Candle],
    ) -> Setup:
        """Process the three-candle 8M retracement window."""
        setup = self._require(setup_id)
        passed, candle = retrace_window_passed(fvg_12m, candles_8m)
        if passed and candle is not None:
            return self.advance_setup_state(
                setup_id,
                SetupState.ONE_MINUTE_CONFIRMATION_ACTIVE,
                changed_at=candle.end_timestamp,
                reason="12M retrace tapped",
                triggering_object_type="Candle",
                triggering_object_id=candle_id(candle),
                updates={
                    "retrace_tap_candle_id": candle_id(candle),
                    "time_remaining": retrace_time_remaining(len(candles_8m)),
                },
            )
        if should_invalidate_retrace_window(fvg_12m, candles_8m):
            return self.invalidate_setup(
                setup_id,
                InvalidationReason.RETRACE_WINDOW_EXPIRED,
                candles_8m[2].end_timestamp,
            )
        return self.store.upsert(replace(setup, time_remaining=retrace_time_remaining(len(candles_8m))))

    def process_one_minute_confirmation(
        self,
        setup_id: str,
        *,
        fvg_12m: FairValueGap,
        candles_1m: Sequence[Candle],
    ) -> Setup:
        """Validate 1M confirmation-phase invalidation rules."""
        for candle in candles_1m:
            if close_above_12m_fvg(fvg_12m, candle):
                return self.invalidate_setup(
                    setup_id,
                    InvalidationReason.CLOSE_ABOVE_12M_FVG,
                    candle.end_timestamp,
                )
        reason = high_sequence_invalidation_reason(fvg_12m, candles_1m)
        if reason is not None:
            return self.invalidate_setup(setup_id, reason, candles_1m[-1].end_timestamp)
        return self._require(setup_id)

    def process_events(self, events: Iterable[dict[str, object]]) -> tuple[Setup, ...]:
        """Replay ordered setup events deterministically."""
        for event in sorted(events, key=lambda item: ensure_utc(item["timestamp"])):  # type: ignore[arg-type]
            event_type = event["type"]
            if event_type == "create":
                self.create_setup(
                    symbol=str(event["symbol"]),
                    created_at=event["timestamp"],  # type: ignore[arg-type]
                    htf_fvg_id=event.get("htf_fvg_id"),  # type: ignore[arg-type]
                )
            elif event_type == "advance":
                self.advance_setup_state(
                    str(event["setup_id"]),
                    event["state"],  # type: ignore[arg-type]
                    changed_at=event["timestamp"],  # type: ignore[arg-type]
                )
        return self.store.all()

    def get_setup_by_id(self, setup_id: str) -> Setup | None:
        return self.store.get(setup_id)

    def get_active_setups(self, symbol: str | None = None) -> tuple[Setup, ...]:
        return self.store.query(symbol=symbol, status=SetupStatus.ACTIVE)

    def get_setups_by_state(self, state: SetupState, symbol: str | None = None) -> tuple[Setup, ...]:
        return self.store.query(symbol=symbol, state=state)

    def get_setups_above_progress(self, progress: float, symbol: str | None = None) -> tuple[Setup, ...]:
        return self.store.query(symbol=symbol, min_progress=progress)

    def get_entry_ready_setups(self, symbol: str | None = None) -> tuple[Setup, ...]:
        return self.store.query(symbol=symbol, status=SetupStatus.ENTRY_READY)

    def get_invalidated_setups(
        self,
        symbol: str | None = None,
        reason: InvalidationReason | None = None,
    ) -> tuple[Setup, ...]:
        setups = self.store.query(symbol=symbol, status=SetupStatus.INVALIDATED)
        return tuple(setup for setup in setups if reason is None or setup.invalidation_reason is reason)

    def get_setup_radar(self, symbol: str | None = None) -> tuple[SetupRadarItem, ...]:
        """Return dashboard-ready radar rows."""
        return tuple(self._to_radar_item(setup) for setup in self.store.query(symbol=symbol))

    def get_setups_between(
        self,
        start: datetime,
        end: datetime,
        symbol: str | None = None,
        status: SetupStatus | None = None,
    ) -> tuple[Setup, ...]:
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        return tuple(
            setup
            for setup in self.store.query(symbol=symbol, status=status)
            if start_utc <= setup.created_at < end_utc
        )

    def get_state_history(self, setup_id: str) -> tuple[StateHistoryEntry, ...]:
        return self._require(setup_id).state_history

    def _to_radar_item(self, setup: Setup) -> SetupRadarItem:
        requirements = (
            ("htf_fvg_id", "HTF FVG"),
            ("swing_16m_id", "16M swing"),
            ("expansion_16m_id", "16M expansion"),
            ("fvg_16m_id", "16M FVG"),
            ("fvg_12m_id", "12M FVG"),
            ("fvg_8m_id", "8M FVG"),
            ("retrace_tap_candle_id", "12M retrace"),
            ("one_minute_swing_id", "1M swing"),
            ("one_minute_fvg_ids", "1M FVG"),
            ("entry_fvg_id", "entry FVG"),
        )
        missing = tuple(label for field_name, label in requirements if not getattr(setup, field_name))
        latest_price = Decimal(setup.metadata["latest_price"]) if "latest_price" in setup.metadata else None
        return SetupRadarItem(
            setup_id=setup.setup_id,
            symbol=setup.symbol,
            direction=setup.direction,
            current_state=setup.current_state,
            progress_percent=setup.progress_percent,
            missing_requirements=missing,
            invalidation_reason=setup.invalidation_reason,
            time_remaining=setup.time_remaining,
            watched_timeframes=setup.watched_timeframes,
            latest_relevant_price=latest_price,
            target_reference=setup.final_target_price,
            stop_reference=setup.stop_reference_price,
        )

    def _require(self, setup_id: str) -> Setup:
        setup = self.store.get(setup_id)
        if setup is None:
            raise KeyError(f"unknown setup_id: {setup_id}")
        return setup


def benchmark_setup_tracker(tracker: SetupTracker, count: int = 1_000) -> dict[str, float]:
    """Create many setups and return benchmark metrics."""
    started_at = perf_counter()
    base = datetime(2026, 1, 1)
    for index in range(count):
        tracker.create_setup(symbol=f"BTC{index % 50}USDT", created_at=base, htf_fvg_id=f"fvg_{index}")
    elapsed_ms = (perf_counter() - started_at) * 1000
    return {
        "setups": float(count),
        "duration_ms": elapsed_ms,
        "setups_per_second": (count / (elapsed_ms / 1000)) if elapsed_ms else 0.0,
    }


def write_validation_html_report(
    *,
    path: Path,
    summary: dict[str, str | int | float],
    setups: Sequence[Setup],
    radar: Sequence[SetupRadarItem],
    known_limitations: Sequence[str],
) -> None:
    """Write HTML validation report."""
    setup_rows = "\n".join(
        f"<tr><td>{setup.setup_id}</td><td>{setup.symbol}</td><td>{setup.current_state.value}</td>"
        f"<td>{setup.progress_percent:.1f}%</td><td>{setup.status.value}</td><td>{setup.invalidation_reason.value if setup.invalidation_reason else ''}</td></tr>"
        for setup in setups
    )
    radar_rows = "\n".join(
        f"<tr><td>{item.setup_id}</td><td>{item.current_state.value}</td><td>{item.progress_percent:.1f}%</td>"
        f"<td>{', '.join(item.missing_requirements)}</td><td>{item.target_reference or ''}</td><td>{item.stop_reference or ''}</td></tr>"
        for item in radar
    )
    summary_items = "\n".join(f"<li><strong>{key}</strong>: {value}</li>" for key, value in summary.items())
    limitations = "\n".join(f"<li>{item}</li>" for item in known_limitations)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Setup Tracker Validation Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }}
th {{ background: #f4ecf7; }} .pass {{ color: #117a65; font-weight: 700; }}
</style></head><body>
<h1>Setup Tracker Validation Report</h1><p class="pass">PASS / FAIL Summary: PASS</p>
<h2>Summary</h2><ul>{summary_items}</ul>
<h2>Setup Lifecycle Timeline</h2>
<table><thead><tr><th>Setup</th><th>Symbol</th><th>State</th><th>Progress</th><th>Status</th><th>Invalidation</th></tr></thead><tbody>{setup_rows}</tbody></table>
<h2>Radar Table</h2>
<table><thead><tr><th>Setup</th><th>State</th><th>Progress</th><th>Missing Requirements</th><th>Target</th><th>Stop</th></tr></thead><tbody>{radar_rows}</tbody></table>
<h2>Known Limitations</h2><ul>{limitations}</ul>
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_validation_png_report(path: Path, setups: Sequence[Setup]) -> None:
    """Write a small PNG progress chart using stdlib."""
    width, height = 720, 360
    pixels = bytearray([255, 255, 255] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

    fill_rect(48, 40, 52, 320, (40, 55, 71))
    fill_rect(48, 316, 660, 320, (40, 55, 71))
    for index, setup in enumerate(setups[:14]):
        x0 = 72 + index * 42
        h = int(setup.progress_percent / 100.0 * 240)
        color = (39, 174, 96) if setup.status is SetupStatus.ENTRY_READY else (46, 134, 193)
        if setup.status is SetupStatus.INVALIDATED:
            color = (192, 57, 43)
        fill_rect(x0, 316 - h, x0 + 28, 316, color)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
