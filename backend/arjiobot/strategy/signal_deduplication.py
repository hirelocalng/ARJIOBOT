"""Signal deduplication helpers."""

from __future__ import annotations

from arjiobot.strategy.strategy_models import SignalStatus, TradeSignal


def has_generated_signal_for_setup(signals: list[TradeSignal], setup_id: str) -> bool:
    """Return whether a generated/active signal already exists for setup."""
    return any(signal.setup_id == setup_id and signal.status is SignalStatus.GENERATED for signal in signals)
