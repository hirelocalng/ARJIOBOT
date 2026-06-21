"""Radar/setup route tests."""

from datetime import datetime, timezone

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.setup_tracker.setup_models import InvalidationReason, Setup, SetupDirection, SetupState, SetupStatus, build_setup_id


def test_radar_starts_empty_without_real_tracked_setup() -> None:
    api = client()
    radar = api.get("/api/radar").json()["data"]

    assert radar == []
    assert api.get("/api/setups").json()["data"] == []
    assert api.get("/api/setups/entry-ready").json()["data"] == []
    assert api.get("/api/setups/progress/50").json()["data"] == []
    assert api.get("/api/setups/in-progress").json()["data"] == []
    assert api.get("/api/setups/completed").json()["data"] == []
    assert api.get("/api/setups/invalidated").json()["data"] == []


def _make_setup(**overrides: object) -> Setup:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values: dict[str, object] = {
        "setup_id": build_setup_id(symbol="BTCUSDT", direction=SetupDirection.BEARISH, created_at=created_at, htf_fvg_id="htf"),
        "symbol": "BTCUSDT",
        "direction": SetupDirection.BEARISH,
        "current_state": SetupState.SWING_16M_CONFIRMED,
        "progress_percent": 20.0,
        "status": SetupStatus.ACTIVE,
        "created_at": created_at,
        "updated_at": created_at,
    }
    values.update(overrides)
    return Setup(**values)


def test_setup_radar_tabs_each_show_only_their_own_category() -> None:
    api = client()
    state = get_state()

    active = _make_setup(setup_id="set_active", symbol="BTCUSDT", progress_percent=35.0, status=SetupStatus.ACTIVE)
    entry_ready = _make_setup(
        setup_id="set_entry_ready",
        symbol="ETHUSDT",
        current_state=SetupState.ENTRY_READY,
        status=SetupStatus.ENTRY_READY,
        progress_percent=100.0,
    )
    completed = _make_setup(
        setup_id="set_completed",
        symbol="SOLUSDT",
        current_state=SetupState.COMPLETED,
        status=SetupStatus.COMPLETED,
        progress_percent=100.0,
    )
    invalidated = _make_setup(
        setup_id="set_invalidated",
        symbol="XRPUSDT",
        current_state=SetupState.INVALIDATED,
        status=SetupStatus.INVALIDATED,
        progress_percent=65.0,
        invalidated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        invalidation_reason=InvalidationReason.RETRACE_WINDOW_EXPIRED,
    )
    for setup in (active, entry_ready, completed, invalidated):
        state.setups[setup.setup_id] = setup

    in_progress = api.get("/api/setups/in-progress").json()["data"]
    completed_rows = api.get("/api/setups/completed").json()["data"]
    invalidated_rows = api.get("/api/setups/invalidated").json()["data"]

    assert [row["setup_id"] for row in in_progress] == ["set_active"]
    assert {row["setup_id"] for row in completed_rows} == {"set_entry_ready", "set_completed"}
    assert [row["setup_id"] for row in invalidated_rows] == ["set_invalidated"]
    # No setup appears in more than one tab, and none shows 100% + a reason.
    for row in completed_rows:
        assert row["invalidation_reason"] is None
    for row in invalidated_rows:
        assert row["progress_percent"] < 100.0
        assert row["invalidation_reason"] is not None
