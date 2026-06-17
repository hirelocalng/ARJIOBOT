"""Service/query tests for Setup Tracker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arjiobot.setup_tracker.demo_setup_tracker import make_candle, make_fvg
from arjiobot.setup_tracker.setup_models import InvalidationReason, SetupState, SetupStatus
from arjiobot.setup_tracker.setup_tracker import SetupTracker, benchmark_setup_tracker


def test_create_and_query_setup() -> None:
    tracker = SetupTracker()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    setup = tracker.create_setup(symbol="BTCUSDT", created_at=created_at, htf_fvg_id="htf")

    assert tracker.get_setup_by_id(setup.setup_id) == setup
    assert tracker.get_active_setups("BTCUSDT") == (setup,)
    assert tracker.get_setups_above_progress(15.0) == (setup,)
    assert tracker.get_state_history(setup.setup_id)


def test_service_stages_and_entry_ready() -> None:
    tracker = SetupTracker()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    setup = tracker.create_setup(symbol="BTCUSDT", created_at=created_at, htf_fvg_id="htf")
    setup = tracker.advance_setup_state(setup.setup_id, SetupState.SWING_16M_CONFIRMED, changed_at=created_at, updates={"swing_16m_id": "swg"})
    setup = tracker.advance_setup_state(setup.setup_id, SetupState.ONE_MINUTE_FVG_CONFIRMED, changed_at=created_at, updates={"one_minute_fvg_ids": ("fvg1",)})
    ready = tracker.mark_entry_ready(setup.setup_id, entry_fvg_id="fvg1", changed_at=created_at)

    assert ready.current_state is SetupState.ENTRY_READY
    assert ready.status is SetupStatus.ENTRY_READY
    assert tracker.get_entry_ready_setups("BTCUSDT") == (ready,)


def test_invalidate_and_expire_queries() -> None:
    tracker = SetupTracker()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    setup = tracker.create_setup(symbol="BTCUSDT", created_at=created_at, htf_fvg_id="htf")
    invalidated = tracker.invalidate_setup(setup.setup_id, InvalidationReason.MANUAL_INVALIDATION, created_at)

    assert tracker.get_invalidated_setups("BTCUSDT", InvalidationReason.MANUAL_INVALIDATION) == (invalidated,)


def test_target_stop_and_radar() -> None:
    tracker = SetupTracker()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    setup = tracker.create_setup(symbol="BTCUSDT", created_at=created_at, htf_fvg_id="htf")
    fvg16 = make_fvg(fvg_id="16", timeframe_minutes=16, lower="80", upper="98", confirmed_index=1, completion_low="76")
    tracker.update_target_references(
        setup.setup_id,
        fvg_16m=fvg16,
        candles_8m_after_16m=[
            make_candle(1, high="100", low="78", close="90"),
            make_candle(2, high="99", low="74", close="88"),
            make_candle(3, high="98", low="79", close="89"),
        ],
    )
    tracker.update_stop_reference(setup.setup_id, Decimal("120"))
    radar = tracker.get_setup_radar("BTCUSDT")[0]

    assert radar.target_reference == Decimal("74")
    assert radar.stop_reference == Decimal("120")
    assert "16M swing" in radar.missing_requirements


def test_process_retrace_window_and_one_minute_invalidations() -> None:
    tracker = SetupTracker()
    setup = tracker.create_setup(symbol="BTCUSDT", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), htf_fvg_id="htf")
    fvg12 = make_fvg(fvg_id="12", timeframe_minutes=12, lower="88", upper="96", confirmed_index=1)

    active = tracker.process_retrace_window(setup.setup_id, fvg_12m=fvg12, candles_8m=[make_candle(1, high="97", low="90", close="92")])
    assert active.current_state is SetupState.ONE_MINUTE_CONFIRMATION_ACTIVE

    invalidated = tracker.process_one_minute_confirmation(
        setup.setup_id,
        fvg_12m=fvg12,
        candles_1m=[make_candle(10, high="98", low="92", close="97", timeframe_minutes=1)],
    )
    assert invalidated.invalidation_reason is InvalidationReason.CLOSE_ABOVE_12M_FVG


def test_retrace_window_expiration() -> None:
    tracker = SetupTracker()
    setup = tracker.create_setup(symbol="BTCUSDT", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), htf_fvg_id="htf")
    fvg12 = make_fvg(fvg_id="12", timeframe_minutes=12, lower="88", upper="96", confirmed_index=1)
    expired = tracker.process_retrace_window(
        setup.setup_id,
        fvg_12m=fvg12,
        candles_8m=[
            make_candle(1, high="87", low="80", close="84"),
            make_candle(2, high="87", low="80", close="84"),
            make_candle(3, high="87", low="80", close="84"),
            make_candle(4, high="87", low="80", close="84"),
        ],
    )
    assert expired.invalidation_reason is InvalidationReason.RETRACE_WINDOW_EXPIRED


def test_fvg_inside_leg_qualification() -> None:
    tracker = SetupTracker()
    setup = tracker.create_setup(symbol="BTCUSDT", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), htf_fvg_id="htf")
    fvg12 = make_fvg(fvg_id="12", timeframe_minutes=12, lower="88", upper="96", confirmed_index=1)

    qualified = tracker.qualify_fvg_inside_16m_leg(
        setup.setup_id,
        fvg=fvg12,
        swing_high_price=Decimal("120"),
        completion_candle_low=Decimal("76"),
        field_name="fvg_12m_id",
        state=SetupState.FVG_12M_CONFIRMED,
    )

    assert qualified.fvg_12m_id == fvg12.fvg_id


def test_setups_between_and_benchmark() -> None:
    tracker = SetupTracker()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tracker.create_setup(symbol="BTCUSDT", created_at=created_at, htf_fvg_id="htf")
    assert tracker.get_setups_between(created_at - timedelta(days=1), created_at + timedelta(days=1))
    metrics = benchmark_setup_tracker(SetupTracker(), count=20)
    assert metrics["setups"] == 20.0
    assert metrics["setups_per_second"] >= 0.0
