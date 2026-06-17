"""Timing/reference tests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.setup_tracker.demo_setup_tracker import make_candle, make_fvg
from arjiobot.setup_tracker.setup_timing import calculate_stop_reference, calculate_target_references, retrace_time_remaining


def test_target_reference_calculation() -> None:
    target_a, target_b, final_target = calculate_target_references(
        fvg_16m=make_fvg(fvg_id="16", timeframe_minutes=16, lower="80", upper="98", confirmed_index=1, completion_low="76"),
        candles_8m_after_16m=[
            make_candle(1, high="100", low="78", close="90"),
            make_candle(2, high="99", low="74", close="88"),
            make_candle(3, high="98", low="79", close="89"),
        ],
    )

    assert target_a == Decimal("76")
    assert target_b == Decimal("74")
    assert final_target == Decimal("74")


def test_stop_reference_and_time_remaining() -> None:
    assert calculate_stop_reference("120") == Decimal("120")
    assert retrace_time_remaining(1) == "2x8M"
    assert retrace_time_remaining(3) == "0x8M"
