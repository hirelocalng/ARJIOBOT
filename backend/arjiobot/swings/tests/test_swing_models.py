"""Tests for Swing Detection Engine data models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from arjiobot.market_data.candle_models import Candle, Timeframe
from arjiobot.swings.swing_models import (
    StructureLabel,
    Swing,
    SwingDetectionResult,
    SwingHigh,
    SwingLow,
    SwingStatus,
    SwingType,
    build_swing_id,
    clamp_strength_score,
    swing_to_record,
)


def make_candle(index: int, *, high: int, low: int, timeframe_minutes: int = 1) -> Candle:
    """Create a valid candle for model tests."""
    timeframe = Timeframe(timeframe_minutes)
    timestamp = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(
        minutes=index * timeframe_minutes
    )
    return Candle(
        symbol="BTCUSDT",
        timeframe=timeframe,
        timestamp=timestamp,
        open=Decimal(low + 1),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high - 1),
        volume=Decimal("10"),
    )


def make_swing_high(**overrides: object) -> SwingHigh:
    """Create a valid swing high model."""
    left = make_candle(0, high=100, low=90)
    middle = make_candle(1, high=110, low=91)
    right = make_candle(2, high=105, low=92)
    source_ids = ("c1", "c2", "c3")
    values = {
        "swing_id": build_swing_id(
            symbol="BTCUSDT",
            timeframe=Timeframe(1),
            timestamp=middle.timestamp,
            swing_type=SwingType.HIGH,
            source_candle_ids=source_ids,
        ),
        "symbol": "btcusdt",
        "timeframe": Timeframe(1),
        "timestamp": middle.timestamp,
        "candidate_detected_at": middle.timestamp,
        "confirmed_at": right.end_timestamp,
        "price": middle.high,
        "candle_index": 1,
        "left_candle": left,
        "middle_candle": middle,
        "right_candle": right,
        "source_candle_ids": source_ids,
    }
    values.update(overrides)
    return SwingHigh(**values)


def make_swing_low(**overrides: object) -> SwingLow:
    """Create a valid swing low model."""
    left = make_candle(0, high=100, low=90)
    middle = make_candle(1, high=99, low=80)
    right = make_candle(2, high=98, low=85)
    source_ids = ("c1", "c2", "c3")
    values = {
        "swing_id": build_swing_id(
            symbol="BTCUSDT",
            timeframe=Timeframe(1),
            timestamp=middle.timestamp,
            swing_type=SwingType.LOW,
            source_candle_ids=source_ids,
        ),
        "symbol": "BTCUSDT",
        "timeframe": Timeframe(1),
        "timestamp": middle.timestamp,
        "candidate_detected_at": middle.timestamp,
        "confirmed_at": right.end_timestamp,
        "price": middle.low,
        "candle_index": 1,
        "left_candle": left,
        "middle_candle": middle,
        "right_candle": right,
        "source_candle_ids": source_ids,
    }
    values.update(overrides)
    return SwingLow(**values)


def test_swing_high_defaults_and_normalization() -> None:
    """Swing high stores the frozen spec defaults."""
    swing = make_swing_high(strength_score=55.5)

    assert swing.symbol == "BTCUSDT"
    assert swing.swing_type is SwingType.HIGH
    assert swing.status is SwingStatus.ACTIVE
    assert swing.strength_score == 55.5
    assert swing.previous_swing_high_id is None
    assert swing.previous_swing_low_id is None
    assert swing.structure_label is None
    assert swing.parent_swing_id is None
    assert not swing.is_strategy_candidate
    assert not swing.touched_htf_fvg
    assert not swing.valid_for_strategy
    assert not swing.expansion_confirmed


def test_swing_low_price_must_match_middle_low() -> None:
    """Swing lows use the middle candle low as price."""
    swing = make_swing_low()

    assert swing.price == swing.middle_candle.low
    assert swing.swing_type is SwingType.LOW


def test_swing_high_price_must_match_middle_high() -> None:
    """Swing highs reject prices that do not match the middle high."""
    with pytest.raises(ValueError, match="swing high price"):
        make_swing_high(price=Decimal("1"))


def test_confirmation_timing_uses_right_candle_close() -> None:
    """A swing is only confirmed when C3 closes."""
    swing = make_swing_high()

    assert swing.candidate_detected_at == swing.middle_candle.timestamp
    assert swing.confirmed_at == swing.right_candle.end_timestamp
    assert swing.confirmed_at > swing.candidate_detected_at


def test_invalid_confirmation_timing_is_rejected() -> None:
    """The model prevents lookahead-unsafe confirmation values."""
    with pytest.raises(ValueError, match="confirmed_at"):
        make_swing_high(confirmed_at=make_candle(2, high=105, low=92).timestamp)


def test_source_candle_ids_are_required() -> None:
    """Replay requires exactly three source candle IDs."""
    with pytest.raises(ValueError, match="exactly three"):
        make_swing_high(source_candle_ids=("c1", "c2"))


def test_strength_score_is_clamped() -> None:
    """Strength score is always within the frozen 0.0-100.0 range."""
    assert clamp_strength_score(-10.0) == 0.0
    assert clamp_strength_score(50.0) == 50.0
    assert clamp_strength_score(120.0) == 100.0
    assert make_swing_high(strength_score=120.0).strength_score == 100.0


def test_broken_status_requires_break_metadata() -> None:
    """Broken swings must store break timing and the candle that caused it."""
    with pytest.raises(ValueError, match="broken_at"):
        make_swing_high(status=SwingStatus.BROKEN)

    broken = make_swing_high(
        status=SwingStatus.BROKEN,
        broken_at=datetime(2026, 1, 1, 0, 4, tzinfo=timezone.utc),
        broken_by_candle_id="c4",
    )

    assert broken.status is SwingStatus.BROKEN
    assert broken.broken_by_candle_id == "c4"


def test_structure_and_strategy_fields_are_supported() -> None:
    """The model carries future strategy and hierarchy state."""
    swing = make_swing_high(
        previous_swing_high_id="prev_high",
        previous_swing_low_id="prev_low",
        structure_label=StructureLabel.LOWER_HIGH,
        parent_swing_id="parent",
        is_strategy_candidate=True,
        touched_htf_fvg=True,
        valid_for_strategy=True,
        expansion_confirmed=True,
    )

    assert swing.previous_swing_high_id == "prev_high"
    assert swing.previous_swing_low_id == "prev_low"
    assert swing.structure_label is StructureLabel.LOWER_HIGH
    assert swing.parent_swing_id == "parent"
    assert swing.is_strategy_candidate
    assert swing.touched_htf_fvg
    assert swing.valid_for_strategy
    assert swing.expansion_confirmed


def test_swing_id_is_deterministic() -> None:
    """The same stable fields generate the same swing ID."""
    timestamp = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    first = build_swing_id(
        symbol="btcusdt",
        timeframe=Timeframe(1),
        timestamp=timestamp,
        swing_type=SwingType.HIGH,
        source_candle_ids=("c1", "c2", "c3"),
    )
    second = build_swing_id(
        symbol="BTCUSDT",
        timeframe=Timeframe(1),
        timestamp=timestamp,
        swing_type=SwingType.HIGH,
        source_candle_ids=("c1", "c2", "c3"),
    )

    assert first == second
    assert first.startswith("swg_")


def test_storage_record_contains_required_persisted_fields() -> None:
    """The record helper includes the frozen minimum storage contract."""
    swing = make_swing_high()

    record = swing_to_record(swing)

    assert record == {
        "swing_id": swing.swing_id,
        "symbol": "BTCUSDT",
        "timeframe": "1M",
        "timestamp": swing.timestamp,
        "confirmed_at": swing.confirmed_at,
        "swing_type": "HIGH",
        "price": swing.price,
        "status": "ACTIVE",
        "strength_score": 0.0,
        "source_candle_ids": ("c1", "c2", "c3"),
    }


def test_detection_result_is_data_only_container() -> None:
    """The result model orders highs and lows without detector logic."""
    high = make_swing_high()
    low = make_swing_low()
    result = SwingDetectionResult(swing_highs=(high,), swing_lows=(low,), duration_ms=1.25)

    assert result.count == 2
    assert tuple(type(swing) for swing in result.all_swings) == (SwingHigh, SwingLow)
    assert isinstance(result.all_swings[0], Swing)
