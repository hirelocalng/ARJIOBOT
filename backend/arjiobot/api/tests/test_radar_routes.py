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
        completed_at=datetime.now(timezone.utc),
    )
    invalidated = _make_setup(
        setup_id="set_invalidated",
        symbol="XRPUSDT",
        current_state=SetupState.INVALIDATED,
        status=SetupStatus.INVALIDATED,
        progress_percent=65.0,
        invalidated_at=datetime.now(timezone.utc),
        invalidation_reason=InvalidationReason.RETRACE_WINDOW_EXPIRED,
    )
    # Mirrors how _append_resolved_setup actually routes a real setup: ACTIVE
    # and pending ENTRY_READY stay in the uncapped in-progress pool,
    # COMPLETED and INVALIDATED live in their own append-only, capped-at-100
    # lists. entry_ready is "pending execution" - still in state.setups
    # because live_automation has not yet resolved it (no execution_status
    # set) - so it belongs in IN PROGRESS, not COMPLETED, until it actually
    # does (see should_leave_in_progress / live_automation.py's _process_setup).
    state.setups[active.setup_id] = active
    state.setups[entry_ready.setup_id] = entry_ready
    state.completed_setups.insert(0, completed)
    state.invalidated_setups.insert(0, invalidated)

    in_progress = api.get("/api/setups/in-progress").json()["data"]
    completed_rows = api.get("/api/setups/completed").json()["data"]
    invalidated_rows = api.get("/api/setups/invalidated").json()["data"]

    assert {row["setup_id"] for row in in_progress} == {"set_active", "set_entry_ready"}
    assert [row["setup_id"] for row in completed_rows] == ["set_completed"]
    assert [row["setup_id"] for row in invalidated_rows] == ["set_invalidated"]
    # No setup appears in more than one tab, and none shows 100% + a reason.
    for row in completed_rows:
        assert row["invalidation_reason"] is None
    for row in invalidated_rows:
        assert row["progress_percent"] < 100.0
        assert row["invalidation_reason"] is not None


def test_pending_execution_setup_at_100_percent_stays_in_in_progress() -> None:
    """FIX 3, the explicit scenario: a real ENTRY_READY setup at 100%
    progress with no execution_status yet ("pending execution" - execution
    has not confirmed or rejected it) must stay in the IN PROGRESS list, with
    its execution_status null (the frontend shows the "Pending execution"
    badge for exactly this), and must not appear in COMPLETED."""
    api = client()
    state = get_state()

    pending = _make_setup(
        setup_id="set_pending_exec",
        symbol="BTCUSDT",
        current_state=SetupState.ENTRY_READY,
        status=SetupStatus.ENTRY_READY,
        progress_percent=100.0,
    )
    state.setups[pending.setup_id] = pending

    in_progress = api.get("/api/setups/in-progress").json()["data"]
    completed_rows = api.get("/api/setups/completed").json()["data"]

    assert [row["setup_id"] for row in in_progress] == ["set_pending_exec"]
    assert in_progress[0]["progress_percent"] == 100.0
    assert in_progress[0]["execution_status"] is None
    assert completed_rows == []


def test_per_stage_columns_stay_in_sync_with_progress_and_state() -> None:
    """radar_record() used to read setup.profile_f_status, an attribute no
    real Setup instance ever sets - every per-stage column (16M FVG,
    Expansion, 12M FVG, 8M Count, 12M Entry) silently rendered as a
    placeholder ("WAITING") regardless of real progress, including on rows
    where current_state/progress_percent correctly showed COMPLETED/100%.
    The per-stage fields must now be derived from progress_percent, which is
    a monotonic high-water mark that can only advance by actually passing
    each prior stage in order."""
    api = client()
    state = get_state()

    early = _make_setup(setup_id="set_early", symbol="BTCUSDT", current_state=SetupState.SWING_16M_CONFIRMED, progress_percent=20.0)
    mid = _make_setup(setup_id="set_mid", symbol="ETHUSDT", current_state=SetupState.FVG_12M_CONFIRMED, progress_percent=65.0)
    done = _make_setup(setup_id="set_done", symbol="SOLUSDT", current_state=SetupState.ENTRY_READY, status=SetupStatus.ENTRY_READY, progress_percent=100.0)
    for setup in (early, mid, done):
        state.setups[setup.setup_id] = setup

    rows = {row["setup_id"]: row for row in api.get("/api/radar").json()["data"]}

    # Only the swing stage (20%) has passed - every later stage column must
    # still read WAITING, not a stale/incorrect CONFIRMED.
    assert rows["set_early"]["expansion_ratio"] == "WAITING"
    assert rows["set_early"]["fvg_16m_status"] == "WAITING"
    assert rows["set_early"]["fvg_12m_status"] == "WAITING"
    assert rows["set_early"]["eight_minute_candle_count_after_16m_fvg"] == "WAITING"
    assert rows["set_early"]["entry_candle_boundary_respected"] is False

    # Passed through 12M FVG (65%) - everything up to and including that
    # stage must read CONFIRMED, but 8M/entry (not yet reached) stay WAITING.
    assert rows["set_mid"]["expansion_ratio"] == "CONFIRMED"
    assert rows["set_mid"]["fvg_16m_status"] == "CONFIRMED"
    assert rows["set_mid"]["fvg_12m_status"] == "CONFIRMED"
    assert rows["set_mid"]["eight_minute_candle_count_after_16m_fvg"] == "WAITING"
    assert rows["set_mid"]["entry_candle_boundary_respected"] is False

    # 100% complete - this is the exact bug report: every stage must show
    # CONFIRMED here, not WAITING next to a COMPLETED/100% state.
    assert rows["set_done"]["current_state"] == "ENTRY_READY"
    assert rows["set_done"]["progress_percent"] == 100.0
    assert rows["set_done"]["expansion_ratio"] == "CONFIRMED"
    assert rows["set_done"]["fvg_16m_status"] == "CONFIRMED"
    assert rows["set_done"]["fvg_12m_status"] == "CONFIRMED"
    assert rows["set_done"]["eight_minute_candle_count_after_16m_fvg"] == "CONFIRMED"
    assert rows["set_done"]["entry_candle_boundary_respected"] is True
