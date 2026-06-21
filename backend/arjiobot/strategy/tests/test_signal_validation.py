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
        # make_entry_ready_setup()'s progress_percent (100) is irrelevant to
        # this test but collides with the "can't be 100% and invalidated"
        # invariant once invalidation_reason is set below.
        progress_percent=40.0,
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


def _make_bullish_entry_ready_setup(*, latest_price: str = "90"):
    """Mirror of make_entry_ready_setup's bearish fixture: stop(60) < entry(90) < target(110)."""
    return replace(
        make_entry_ready_setup(latest_price=latest_price),
        direction=SetupDirection.BULLISH,
        stop_reference_price=Decimal("60"),
        final_target_price=Decimal("110"),
    )


def test_accepts_bullish_setup_mirroring_bearish_criteria() -> None:
    result = validate_setup_for_signal(_make_bullish_entry_ready_setup(), checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert result.validation_passed
    assert result.rejection_reason is None


def test_rejects_invalid_stop_target_relationship() -> None:
    setup = replace(make_entry_ready_setup(), stop_reference_price=Decimal("60"))
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert result.rejection_reason is SignalRejectionReason.INVALID_STOP_TARGET_RELATIONSHIP


def test_rejects_invalid_stop_target_relationship_bullish() -> None:
    setup = replace(_make_bullish_entry_ready_setup(), stop_reference_price=Decimal("120"))
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert result.rejection_reason is SignalRejectionReason.INVALID_STOP_TARGET_RELATIONSHIP


def test_rejects_target_already_reached() -> None:
    setup = replace(make_entry_ready_setup(latest_price="65"))
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert result.rejection_reason is SignalRejectionReason.TARGET_ALREADY_REACHED


def test_rejects_target_already_reached_bullish() -> None:
    setup = replace(_make_bullish_entry_ready_setup(latest_price="115"))
    result = validate_setup_for_signal(setup, checked_at=setup.updated_at)

    assert result.rejection_reason is SignalRejectionReason.TARGET_ALREADY_REACHED

