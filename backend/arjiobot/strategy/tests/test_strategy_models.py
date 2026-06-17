"""Model tests for Strategy Engine."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from arjiobot.setup_tracker.setup_models import SetupDirection, SetupState
from arjiobot.strategy.strategy_models import (
    EntryReferenceType,
    SignalAction,
    SignalRejectionReason,
    SignalStatus,
    SignalValidationResult,
    TradeSignal,
    build_signal_id,
    signal_to_record,
)


def make_signal(**overrides: object) -> TradeSignal:
    """Create a valid generated signal."""
    generated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = {
        "signal_id": build_signal_id(setup_id="setup_1", generated_at=generated_at, status=SignalStatus.GENERATED),
        "setup_id": "setup_1",
        "symbol": "btcusdt",
        "direction": SetupDirection.BEARISH,
        "action": SignalAction.MARKET_SELL_READY,
        "status": SignalStatus.GENERATED,
        "created_at": generated_at,
        "updated_at": generated_at,
        "generated_at": generated_at,
        "entry_reference_type": EntryReferenceType.MARKET_SELL,
        "entry_reference_price": Decimal("90"),
        "stop_reference_price": Decimal("120"),
        "final_target_price": Decimal("70"),
        "validation_passed": True,
        "source_state": SetupState.ENTRY_READY,
        "source_progress_percent": 100.0,
    }
    values.update(overrides)
    return TradeSignal(**values)


def test_signal_model_creation_and_record() -> None:
    signal = make_signal()
    record = signal_to_record(signal)

    assert signal.symbol == "BTCUSDT"
    assert signal.status is SignalStatus.GENERATED
    assert record["signal_id"] == signal.signal_id
    assert record["action"] == "MARKET_SELL_READY"


def test_rejected_signal_requires_reason() -> None:
    with pytest.raises(ValueError, match="rejection_reason"):
        make_signal(status=SignalStatus.REJECTED, validation_passed=False)

    rejected = make_signal(
        signal_id="sig_rejected",
        status=SignalStatus.REJECTED,
        validation_passed=False,
        rejection_reason=SignalRejectionReason.SETUP_NOT_ENTRY_READY,
    )
    assert rejected.rejection_reason is SignalRejectionReason.SETUP_NOT_ENTRY_READY


def test_signal_id_is_deterministic() -> None:
    generated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = build_signal_id(setup_id="setup", generated_at=generated_at, status=SignalStatus.GENERATED)
    second = build_signal_id(setup_id="setup", generated_at=generated_at, status=SignalStatus.GENERATED)

    assert first == second
    assert first.startswith("sig_")


def test_validation_result_normalizes_time() -> None:
    result = SignalValidationResult(True, (), None, datetime(2026, 1, 1))

    assert result.checked_at.tzinfo is not None

