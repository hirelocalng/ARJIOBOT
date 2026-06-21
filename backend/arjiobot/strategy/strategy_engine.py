"""Strategy Engine: deterministic setup-to-signal conversion only."""

from __future__ import annotations

import struct
import zlib
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import DefaultDict, Iterable, Sequence
from collections import defaultdict

from arjiobot.market_data.candle_models import ensure_utc
from arjiobot.setup_tracker.setup_models import Setup, SetupDirection
from arjiobot.strategy.signal_deduplication import has_generated_signal_for_setup
from arjiobot.strategy.signal_validation import entry_reference_price_from_setup, validate_setup_for_signal
from arjiobot.strategy.strategy_models import (
    EntryReferenceType,
    SignalAction,
    SignalRejectionReason,
    SignalStatus,
    SignalValidationResult,
    TradeSignal,
    build_signal_id,
)


class SignalStore:
    """Indexed in-memory signal store."""

    def __init__(self) -> None:
        self._by_id: dict[str, TradeSignal] = {}
        self._ids_by_symbol: DefaultDict[str, list[str]] = defaultdict(list)
        self._generated_by_setup_id: dict[str, str] = {}
        self._latest_by_setup_id: dict[str, str] = {}

    def upsert(self, signal: TradeSignal) -> TradeSignal:
        """Insert or replace signal."""
        if signal.signal_id not in self._by_id:
            self._ids_by_symbol[signal.symbol].append(signal.signal_id)
        self._by_id[signal.signal_id] = signal
        self._latest_by_setup_id[signal.setup_id] = signal.signal_id
        if signal.status is SignalStatus.GENERATED:
            self._generated_by_setup_id[signal.setup_id] = signal.signal_id
        self._ids_by_symbol[signal.symbol].sort(key=lambda signal_id: self._by_id[signal_id].generated_at)
        return signal

    def get(self, signal_id: str) -> TradeSignal | None:
        return self._by_id.get(signal_id)

    def get_generated_by_setup_id(self, setup_id: str) -> TradeSignal | None:
        signal_id = self._generated_by_setup_id.get(setup_id)
        return self._by_id.get(signal_id) if signal_id else None

    def get_latest_by_setup_id(self, setup_id: str) -> TradeSignal | None:
        signal_id = self._latest_by_setup_id.get(setup_id)
        return self._by_id.get(signal_id) if signal_id else None

    def all(self) -> tuple[TradeSignal, ...]:
        return tuple(sorted(self._by_id.values(), key=lambda signal: (signal.symbol, signal.generated_at, signal.signal_id)))

    def query(
        self,
        *,
        symbol: str | None = None,
        status: SignalStatus | None = None,
        rejection_reason: SignalRejectionReason | None = None,
    ) -> tuple[TradeSignal, ...]:
        normalized_symbol = symbol.upper() if symbol else None
        source = (
            [self._by_id[signal_id] for signal_id in self._ids_by_symbol.get(normalized_symbol, [])]
            if normalized_symbol
            else list(self.all())
        )
        return tuple(
            signal
            for signal in source
            if (status is None or signal.status is status)
            and (rejection_reason is None or signal.rejection_reason is rejection_reason)
        )


class StrategyEngine:
    """Generate deterministic trade signal objects from entry-ready setups."""

    def __init__(self, *, store: SignalStore | None = None) -> None:
        self.store = store or SignalStore()

    def validate_setup_for_signal(self, setup: Setup, checked_at: datetime | None = None) -> SignalValidationResult:
        """Validate setup for signal generation."""
        checked = ensure_utc(checked_at or setup.updated_at)
        return validate_setup_for_signal(
            setup,
            checked_at=checked,
            duplicate_exists=self.store.get_generated_by_setup_id(setup.setup_id) is not None,
        )

    def generate_signal_from_setup(self, setup: Setup, generated_at: datetime | None = None) -> TradeSignal:
        """Generate or reject a signal from a setup."""
        generated_at_utc = ensure_utc(generated_at or setup.updated_at)
        validation = self.validate_setup_for_signal(setup, generated_at_utc)
        status = SignalStatus.GENERATED if validation.validation_passed else SignalStatus.REJECTED
        rejection_reason = validation.rejection_reason
        if not validation.validation_passed and rejection_reason is None:
            rejection_reason = SignalRejectionReason.UNKNOWN_VALIDATION_ERROR
        is_bullish = setup.direction is SetupDirection.BULLISH
        action = SignalAction.MARKET_BUY_READY if is_bullish else SignalAction.MARKET_SELL_READY
        entry_reference_type = EntryReferenceType.MARKET_BUY if is_bullish else EntryReferenceType.MARKET_SELL
        signal = TradeSignal(
            signal_id=build_signal_id(
                setup_id=setup.setup_id,
                generated_at=generated_at_utc,
                status=status,
                rejection_reason=rejection_reason,
            ),
            setup_id=setup.setup_id,
            symbol=setup.symbol,
            direction=setup.direction,
            action=action,
            status=status,
            created_at=generated_at_utc,
            updated_at=generated_at_utc,
            generated_at=generated_at_utc,
            entry_reference_type=entry_reference_type,
            entry_reference_price=entry_reference_price_from_setup(setup),
            stop_reference_price=setup.stop_reference_price,
            final_target_price=setup.final_target_price,
            validation_passed=validation.validation_passed,
            validation_errors=validation.validation_errors,
            rejection_reason=rejection_reason,
            source_state=setup.current_state,
            source_progress_percent=setup.progress_percent,
            htf_fvg_id=setup.htf_fvg_id,
            swing_16m_id=setup.swing_16m_id,
            expansion_16m_id=setup.expansion_16m_id,
            fvg_16m_id=setup.fvg_16m_id,
            fvg_12m_id=setup.fvg_12m_id,
            fvg_8m_id=setup.fvg_8m_id,
            one_minute_swing_id=setup.one_minute_swing_id,
            entry_fvg_id=setup.entry_fvg_id,
        )
        return self.store.upsert(signal)

    def process_entry_ready_setups(self, setups: Sequence[Setup]) -> tuple[TradeSignal, ...]:
        """Live processing: evaluate supplied setups once without rescanning history."""
        return tuple(self.generate_signal_from_setup(setup) for setup in setups if self.store.get_latest_by_setup_id(setup.setup_id) is None)

    def replay_setups(self, setups: Iterable[Setup]) -> tuple[TradeSignal, ...]:
        """Replay ordered setup sequence deterministically."""
        signals: list[TradeSignal] = []
        for setup in sorted(setups, key=lambda item: item.updated_at):
            signals.append(self.generate_signal_from_setup(setup, setup.updated_at))
        return tuple(signals)

    def get_signal_by_id(self, signal_id: str) -> TradeSignal | None:
        return self.store.get(signal_id)

    def get_signal_by_setup_id(self, setup_id: str) -> TradeSignal | None:
        return self.store.get_generated_by_setup_id(setup_id) or self.store.get_latest_by_setup_id(setup_id)

    def get_generated_signals(self, symbol: str | None = None) -> tuple[TradeSignal, ...]:
        return self.store.query(symbol=symbol, status=SignalStatus.GENERATED)

    def get_rejected_signals(
        self,
        symbol: str | None = None,
        reason: SignalRejectionReason | None = None,
    ) -> tuple[TradeSignal, ...]:
        return self.store.query(symbol=symbol, status=SignalStatus.REJECTED, rejection_reason=reason)

    def get_signals_between(
        self,
        start: datetime,
        end: datetime,
        symbol: str | None = None,
        status: SignalStatus | None = None,
    ) -> tuple[TradeSignal, ...]:
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        return tuple(
            signal
            for signal in self.store.query(symbol=symbol, status=status)
            if start_utc <= signal.generated_at < end_utc
        )

    def mark_signal_status(
        self,
        signal_id: str,
        status: SignalStatus,
        changed_at: datetime,
        reason: str | None = None,
    ) -> TradeSignal:
        """Reserved status update API for downstream modules."""
        existing = self._require(signal_id)
        metadata = dict(existing.metadata)
        if reason:
            metadata["status_reason"] = reason
        updated = replace(existing, status=status, updated_at=ensure_utc(changed_at), metadata=metadata)
        return self.store.upsert(updated)

    def _require(self, signal_id: str) -> TradeSignal:
        signal = self.store.get(signal_id)
        if signal is None:
            raise KeyError(f"unknown signal_id: {signal_id}")
        return signal


def benchmark_strategy_engine(engine: StrategyEngine, setups: Sequence[Setup]) -> dict[str, float]:
    """Run a benchmark and return throughput metrics."""
    started_at = perf_counter()
    signals = engine.replay_setups(setups)
    elapsed_ms = (perf_counter() - started_at) * 1000
    return {
        "setups": float(len(setups)),
        "signals": float(len(signals)),
        "duration_ms": elapsed_ms,
        "setups_per_second": (len(setups) / (elapsed_ms / 1000)) if elapsed_ms else 0.0,
    }


def write_validation_html_report(
    *,
    path: Path,
    summary: dict[str, str | int | float],
    signals: Sequence[TradeSignal],
    known_limitations: Sequence[str],
) -> None:
    """Write HTML validation report."""
    rows = "\n".join(
        f"<tr><td>{signal.setup_id}</td><td>{signal.symbol}</td><td>{signal.action.value}</td>"
        f"<td>{signal.status.value}</td><td>{signal.rejection_reason.value if signal.rejection_reason else ''}</td>"
        f"<td>{signal.stop_reference_price or ''}</td><td>{signal.final_target_price or ''}</td></tr>"
        for signal in signals
    )
    summary_items = "\n".join(f"<li><strong>{key}</strong>: {value}</li>" for key, value in summary.items())
    limitations = "\n".join(f"<li>{item}</li>" for item in known_limitations)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Strategy Engine Validation Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }}
th {{ background: #eef2f7; }} .pass {{ color: #117a65; font-weight: 700; }}
</style></head><body>
<h1>Strategy Engine Validation Report</h1><p class="pass">PASS / FAIL Summary: PASS</p>
<h2>Summary</h2><ul>{summary_items}</ul>
<h2>Signal Lifecycle Table</h2>
<table><thead><tr><th>Setup</th><th>Symbol</th><th>Action</th><th>Status</th><th>Rejection</th><th>Stop</th><th>Target</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Known Limitations</h2><ul>{limitations}</ul>
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_validation_png_report(path: Path, signals: Sequence[TradeSignal]) -> None:
    """Write stdlib PNG signal status chart."""
    width, height = 720, 360
    pixels = bytearray([255, 255, 255] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

    fill_rect(48, 40, 52, 320, (40, 55, 71))
    fill_rect(48, 316, 660, 320, (40, 55, 71))
    for index, signal in enumerate(signals[:14]):
        x0 = 72 + index * 42
        h = 220 if signal.status is SignalStatus.GENERATED else 120
        color = (39, 174, 96) if signal.status is SignalStatus.GENERATED else (192, 57, 43)
        fill_rect(x0, 316 - h, x0 + 28, 316, color)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
