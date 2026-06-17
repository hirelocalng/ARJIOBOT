"""Model tests for Setup Tracker."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from arjiobot.setup_tracker.setup_models import (
    InvalidationReason,
    Setup,
    SetupDirection,
    SetupState,
    SetupStatus,
    build_setup_id,
    clamp_progress,
    setup_to_record,
)


def make_setup(**overrides: object) -> Setup:
    """Create valid setup."""
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = {
        "setup_id": build_setup_id(symbol="BTCUSDT", direction=SetupDirection.BEARISH, created_at=created_at, htf_fvg_id="htf"),
        "symbol": "btcusdt",
        "direction": SetupDirection.BEARISH,
        "current_state": SetupState.WATCHING_HTF_FVG,
        "progress_percent": 150.0,
        "status": SetupStatus.ACTIVE,
        "created_at": created_at,
        "updated_at": created_at,
        "htf_fvg_id": "htf",
    }
    values.update(overrides)
    return Setup(**values)


def test_setup_model_defaults_and_normalization() -> None:
    setup = make_setup()

    assert setup.symbol == "BTCUSDT"
    assert setup.direction is SetupDirection.BEARISH
    assert setup.progress_percent == 100.0
    assert setup.status is SetupStatus.ACTIVE


def test_invalidated_setup_requires_reason_and_time() -> None:
    with pytest.raises(ValueError, match="reason"):
        make_setup(current_state=SetupState.INVALIDATED, status=SetupStatus.INVALIDATED)

    setup = make_setup(
        current_state=SetupState.INVALIDATED,
        status=SetupStatus.INVALIDATED,
        invalidated_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        invalidation_reason=InvalidationReason.MANUAL_INVALIDATION,
    )
    assert setup.invalidation_reason is InvalidationReason.MANUAL_INVALIDATION


def test_setup_id_is_deterministic() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = build_setup_id(symbol="btcusdt", direction=SetupDirection.BEARISH, created_at=created_at, htf_fvg_id="a")
    second = build_setup_id(symbol="BTCUSDT", direction=SetupDirection.BEARISH, created_at=created_at, htf_fvg_id="a")

    assert first == second
    assert first.startswith("set_")


def test_record_and_progress_clamp() -> None:
    setup = make_setup(progress_percent=42.0)
    record = setup_to_record(setup)

    assert record["setup_id"] == setup.setup_id
    assert record["progress_percent"] == 42.0
    assert clamp_progress(-1) == 0.0
    assert clamp_progress(101) == 100.0

