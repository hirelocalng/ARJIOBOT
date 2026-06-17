"""Lifecycle tests for the FVG Engine."""

from __future__ import annotations

from datetime import datetime, timezone

from arjiobot.fvg.fvg import FVGDetectionEngine
from arjiobot.fvg.fvg_lifecycle import transition_fvg
from arjiobot.fvg.fvg_models import FVGLifecycleState
from arjiobot.fvg.tests.test_fvg_detection import bearish_window, make_candle
from arjiobot.fvg.tests.test_fvg_models import make_fvg


def test_lifecycle_transition_keeps_status_in_sync() -> None:
    """Lifecycle helper syncs status and lifecycle_state."""
    updated = transition_fvg(make_fvg(), FVGLifecycleState.FILLED)

    assert updated.status is FVGLifecycleState.FILLED
    assert updated.lifecycle_state is FVGLifecycleState.FILLED


def test_service_mark_tapped_tracks_touch_count() -> None:
    """Tap updates happen through the service API."""
    engine = FVGDetectionEngine()
    fvg = engine.detect_fvgs(bearish_window()).fvgs[0]

    tapped = engine.mark_tapped(fvg.fvg_id, make_candle(4, open_="90", high="94", low="89", close="91"), fvg.confirmed_at)

    assert tapped.touched
    assert tapped.touch_count == 1
    assert tapped.status is FVGLifecycleState.TAPPED
    assert engine.get_tapped_fvgs("BTCUSDT", "1M") == (tapped,)


def test_service_invalidation_tracks_reason() -> None:
    """Invalidation is centralized."""
    engine = FVGDetectionEngine()
    fvg = engine.detect_fvgs(bearish_window()).fvgs[0]

    invalidated = engine.invalidate_fvg(
        fvg.fvg_id,
        "tap candle closed above FVG",
        datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert invalidated.status is FVGLifecycleState.INVALIDATED
    assert invalidated.invalidation_reason == "tap candle closed above FVG"


def test_service_update_lifecycle_state() -> None:
    """Service lifecycle updates replace stored objects."""
    engine = FVGDetectionEngine()
    fvg = engine.detect_fvgs(bearish_window()).fvgs[0]

    filled = engine.update_lifecycle_state(fvg.fvg_id, FVGLifecycleState.FILLED)

    assert engine.get_fvg_by_id(fvg.fvg_id) == filled
    assert filled.status is FVGLifecycleState.FILLED

