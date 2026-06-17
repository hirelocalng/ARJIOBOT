"""Model tests for the FVG Engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from arjiobot.fvg.fvg_models import (
    FVGDirection,
    FVGLifecycleState,
    FairValueGap,
    build_fvg_id,
    clamp_score,
    fvg_to_record,
)
from arjiobot.market_data.candle_models import Timeframe


def make_fvg(**overrides: object) -> FairValueGap:
    """Create a valid FVG model."""
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    values = {
        "fvg_id": build_fvg_id(
            symbol="BTCUSDT",
            timeframe=Timeframe(1),
            direction=FVGDirection.BEARISH,
            c1_id="c1",
            c2_id="c2",
            c3_id="c3",
        ),
        "symbol": "btcusdt",
        "timeframe": Timeframe(1),
        "direction": FVGDirection.BEARISH,
        "timestamp": start + timedelta(minutes=1),
        "confirmed_at": start + timedelta(minutes=3),
        "c1_id": "c1",
        "c2_id": "c2",
        "c3_id": "c3",
        "c1_timestamp": start,
        "c2_timestamp": start + timedelta(minutes=1),
        "c3_timestamp": start + timedelta(minutes=2),
        "upper_boundary": Decimal("95"),
        "lower_boundary": Decimal("90"),
        "gap_size": Decimal("5"),
        "gap_size_percent": 5.26,
        "strength_score": 120.0,
    }
    values.update(overrides)
    return FairValueGap(**values)


def test_fvg_defaults_and_normalization() -> None:
    """FVG models normalize and store required defaults."""
    fvg = make_fvg()

    assert fvg.symbol == "BTCUSDT"
    assert fvg.status is FVGLifecycleState.ACTIVE
    assert fvg.lifecycle_state is FVGLifecycleState.ACTIVE
    assert not fvg.touched
    assert fvg.touch_count == 0
    assert fvg.strength_score == 100.0


def test_boundaries_and_gap_size_are_validated() -> None:
    """Gap size must match the strict boundaries."""
    with pytest.raises(ValueError, match="gap_size"):
        make_fvg(gap_size=Decimal("4"))
    with pytest.raises(ValueError, match="upper_boundary"):
        make_fvg(upper_boundary=Decimal("90"), lower_boundary=Decimal("95"))


def test_touched_metadata_consistency() -> None:
    """Touched records require touch metadata."""
    with pytest.raises(ValueError, match="touch_count"):
        make_fvg(touched=True)


def test_invalidated_state_requires_reason_and_time() -> None:
    """Invalidation requires reason metadata."""
    with pytest.raises(ValueError, match="invalidated_at"):
        make_fvg(status=FVGLifecycleState.INVALIDATED, lifecycle_state=FVGLifecycleState.INVALIDATED)


def test_fvg_id_is_deterministic() -> None:
    """Stable fields generate stable FVG IDs."""
    first = build_fvg_id(
        symbol="btcusdt",
        timeframe=Timeframe(1),
        direction=FVGDirection.BEARISH,
        c1_id="c1",
        c2_id="c2",
        c3_id="c3",
    )
    second = build_fvg_id(
        symbol="BTCUSDT",
        timeframe=Timeframe(1),
        direction=FVGDirection.BEARISH,
        c1_id="c1",
        c2_id="c2",
        c3_id="c3",
    )

    assert first == second
    assert first.startswith("fvg_")


def test_record_contains_queryable_fields() -> None:
    """Record helper exposes downstream fields."""
    fvg = make_fvg(related_swing_id="swg_1", related_expansion_id="exp_1", is_strategy_fvg=True)
    record = fvg_to_record(fvg)

    assert record["related_swing_id"] == "swg_1"
    assert record["related_expansion_id"] == "exp_1"
    assert record["is_strategy_fvg"] is True


def test_score_clamping() -> None:
    """Scores are clamped to 0 through 100."""
    assert clamp_score(-1.0) == 0.0
    assert clamp_score(40.0) == 40.0
    assert clamp_score(140.0) == 100.0

