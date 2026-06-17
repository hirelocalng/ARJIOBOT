"""Tests for Expansion Candle Engine models."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from arjiobot.market_data.candle_models import Timeframe
from arjiobot.expansion.expansion_models import (
    ExpansionCandle,
    ExpansionDirection,
    build_expansion_id,
    clamp_score,
    expansion_to_record,
)
from arjiobot.swings.swing_models import SwingType


def make_expansion(**overrides: object) -> ExpansionCandle:
    """Create a valid expansion model."""
    timestamp = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    values = {
        "expansion_id": build_expansion_id(
            symbol="BTCUSDT",
            timeframe=Timeframe(1),
            timestamp=timestamp,
            direction=ExpansionDirection.BEARISH,
            swing_id="swg_1",
        ),
        "symbol": "btcusdt",
        "timeframe": Timeframe(1),
        "timestamp": timestamp,
        "direction": ExpansionDirection.BEARISH,
        "swing_id": "swg_1",
        "swing_type": SwingType.HIGH,
        "size": Decimal("30"),
        "expansion_ratio": 2.5,
        "displacement_distance": Decimal("8"),
        "displacement_percent": 26.67,
        "displacement_strength": 26.67,
        "strength_score": 75.0,
    }
    values.update(overrides)
    return ExpansionCandle(**values)


def test_expansion_defaults_and_normalization() -> None:
    """Expansion model stores required defaults."""
    expansion = make_expansion(strength_score=150.0)

    assert expansion.symbol == "BTCUSDT"
    assert expansion.timeframe == Timeframe(1)
    assert expansion.strength_score == 100.0
    assert not expansion.is_fvg_candidate


def test_direction_must_match_swing_type() -> None:
    """Bearish uses swing high and bullish uses swing low."""
    with pytest.raises(ValueError, match="bearish expansions"):
        make_expansion(swing_type=SwingType.LOW)

    bullish = make_expansion(
        direction=ExpansionDirection.BULLISH,
        swing_type=SwingType.LOW,
    )
    assert bullish.direction is ExpansionDirection.BULLISH


def test_required_positive_metrics_are_validated() -> None:
    """Invalid metrics are rejected early."""
    with pytest.raises(ValueError, match="size"):
        make_expansion(size=Decimal("0"))
    with pytest.raises(ValueError, match="displacement_distance"):
        make_expansion(displacement_distance=Decimal("0"))


def test_expansion_id_is_deterministic() -> None:
    """Stable identity fields generate stable IDs."""
    timestamp = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    first = build_expansion_id(
        symbol="btcusdt",
        timeframe=Timeframe(1),
        timestamp=timestamp,
        direction=ExpansionDirection.BEARISH,
        swing_id="swg_1",
    )
    second = build_expansion_id(
        symbol="BTCUSDT",
        timeframe=Timeframe(1),
        timestamp=timestamp,
        direction=ExpansionDirection.BEARISH,
        swing_id="swg_1",
    )

    assert first == second
    assert first.startswith("exp_")


def test_record_contains_downstream_fields() -> None:
    """Record helper includes all required storage fields."""
    expansion = make_expansion(is_fvg_candidate=True)

    record = expansion_to_record(expansion)

    assert record["expansion_id"] == expansion.expansion_id
    assert record["swing_id"] == "swg_1"
    assert record["direction"] == "BEARISH"
    assert record["is_fvg_candidate"] is True


def test_score_clamping() -> None:
    """Scores are clamped to the frozen range."""
    assert clamp_score(-1.0) == 0.0
    assert clamp_score(25.0) == 25.0
    assert clamp_score(125.0) == 100.0
