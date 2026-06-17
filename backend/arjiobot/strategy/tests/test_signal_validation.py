"""Validation tests for Strategy Engine."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from arjiobot.setup_tracker.setup_models import InvalidationReason, SetupDirection, SetupState, SetupStatus
from arjiobot.strategy.demo_strategy import make_entry_ready_setup
from arjiobot.strategy.signal_validation import validate_setup_for_signal
from arjiobot.strategy.strategy_models import SignalRejectionReason


def test_valid_entry_ready_setup_passes_validation() -> None:
    result = validate_setup_for_signal(make_entry_ready_setup(), checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert result.validation_passed
    assert result.rejection_reason is None


def test_rejects_setup_not_entry_ready() -> None:
    setup = replace(make_entry_ready_setup(), current_state=SetupState.WATCHING_HTF_FVG, status=SetupStatus.ACTIVE)
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert not result.validation_passed
    assert result.rejection_reason is SignalRejectionReason.SETUP_NOT_ENTRY_READY


def test_rejects_invalidated_and_expired_setups() -> None:
    invalid = replace(
        make_entry_ready_setup(),
        current_state=SetupState.INVALIDATED,
        status=SetupStatus.INVALIDATED,
        invalidated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        invalidation_reason=InvalidationReason.MANUAL_INVALIDATION,
    )
    expired = replace(make_entry_ready_setup(suffix="2"), current_state=SetupState.EXPIRED, status=SetupStatus.EXPIRED)

    assert validate_setup_for_signal(invalid, checked_at=invalid.updated_at).rejection_reason is SignalRejectionReason.SETUP_INVALIDATED
    assert validate_setup_for_signal(expired, checked_at=expired.updated_at).rejection_reason is SignalRejectionReason.SETUP_EXPIRED


def test_rejects_missing_required_fields() -> None:
    setup = replace(make_entry_ready_setup(), entry_fvg_id=None)
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert result.rejection_reason is SignalRejectionReason.MISSING_REQUIRED_FIELD


def test_rejects_unsupported_direction() -> None:
    setup = replace(make_entry_ready_setup(), direction=SetupDirection.BULLISH)
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert result.rejection_reason is SignalRejectionReason.UNSUPPORTED_DIRECTION


def test_rejects_invalid_stop_target_relationship() -> None:
    setup = replace(make_entry_ready_setup(), stop_reference_price=Decimal("60"))
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert result.rejection_reason is SignalRejectionReason.INVALID_STOP_TARGET_RELATIONSHIP


def test_rejects_target_already_reached() -> None:
    setup = replace(make_entry_ready_setup(latest_price="65"))
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert result.rejection_reason is SignalRejectionReason.TARGET_ALREADY_REACHED

