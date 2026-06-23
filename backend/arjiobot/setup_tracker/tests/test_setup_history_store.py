"""Tests for disk-backed completed/invalidated Setup Radar persistence.

Every test here redirects STORE_PATH/HISTORY_CLEARED_MARKER_PATH to a
pytest tmp_path - never the real backend/data/ files. Writing to the real
path from a test would risk creating the real migration marker outside of
an actual deploy, which would silently skip the real one-time wipe in
production.
"""

from __future__ import annotations

from types import SimpleNamespace

from arjiobot.live_setup_detection import _setup_from_trade
from arjiobot.setup_tracker import setup_history_store
from arjiobot.setup_tracker.setup_models import SetupState, SetupStatus


def _fake_state() -> SimpleNamespace:
    return SimpleNamespace(setups={}, invalidated_setups={}, completed_setups={}, setup_history={})


def _redirect_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(setup_history_store, "STORE_PATH", tmp_path / "setup_history_store.json")
    monkeypatch.setattr(setup_history_store, "HISTORY_CLEARED_MARKER_PATH", tmp_path / ".history_cleared")


def _make_completed_trade(state, *, suffix: str, entry_timestamp: str):
    return _setup_from_trade(
        {
            "trade_id": f"trade_{suffix}",
            "symbol": "ADAUSDT",
            "direction": "BEARISH",
            "entry_timestamp": entry_timestamp,
            "entry_price": "100",
            "stop_loss": "120",
            "take_profit": "80",
            "source_12m_fvg_id": f"fvg12_{suffix}",
            "source_16m_swing_id": f"swing_{suffix}",
            "source_16m_fvg_id": f"fvg16_{suffix}",
        },
        state=state,
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )


def test_save_and_load_round_trips_a_completed_setup_exactly(monkeypatch, tmp_path) -> None:
    """Every field needed to reproduce the same API output after a restart -
    setup_id, timestamps, metadata, and state_history - must survive a
    save/load round trip exactly."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    trade = _make_completed_trade(state, suffix="rt1", entry_timestamp="2026-06-24T01:30:00+00:00")
    state.completed_setups[trade.setup_id] = trade
    state.setup_history[trade.setup_id] = [{"from_state": None, "to_state": "ENTRY_READY", "changed_at": "2026-06-24T01:30:00+00:00", "reason": "test", "source": "TEST"}]

    setup_history_store.save_setup_history_store(state)
    reloaded_state = _fake_state()
    completed_count, invalidated_count = setup_history_store.load_setup_history_store(reloaded_state)

    assert (completed_count, invalidated_count) == (1, 0)
    [reloaded] = reloaded_state.completed_setups.values()
    assert reloaded.setup_id == trade.setup_id
    assert reloaded.completed_at == trade.completed_at
    assert reloaded.created_at == trade.created_at
    assert reloaded.metadata == trade.metadata
    assert reloaded.current_state is SetupState.ENTRY_READY
    assert reloaded.status is SetupStatus.ENTRY_READY
    assert reloaded_state.setup_history[trade.setup_id] == state.setup_history[trade.setup_id]


def test_in_progress_setups_are_never_persisted(monkeypatch, tmp_path) -> None:
    """state.setups (IN PROGRESS) must never be written to or read from
    disk - only completed_setups/invalidated_setups are persisted."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    active = _make_completed_trade(state, suffix="active1", entry_timestamp="2026-06-24T01:30:00+00:00")
    state.setups[active.setup_id] = active  # deliberately placed in IN PROGRESS, not completed_setups
    state.setup_history[active.setup_id] = [{"from_state": None, "to_state": "ACTIVE"}]

    setup_history_store.save_setup_history_store(state)
    reloaded_state = _fake_state()
    setup_history_store.load_setup_history_store(reloaded_state)

    assert reloaded_state.completed_setups == {}
    assert reloaded_state.invalidated_setups == {}
    assert reloaded_state.setups == {}, "IN PROGRESS must never be reloaded from the persisted file"


def test_migration_wipes_a_file_that_already_existed_before_the_marker_did(monkeypatch, tmp_path) -> None:
    """The exact scenario reported: setup_history_store.json already exists
    on disk with old entries (written by a process that never knew about
    the marker file) before this migration code ever runs for the first
    time. The migration must overwrite that pre-existing file with the
    empty state, not merely check for the marker and skip writing because
    the data file happens to already be there."""
    _redirect_paths(monkeypatch, tmp_path)
    # Simulate 100 pre-existing entries on disk, written before the marker
    # file concept existed - no HISTORY_CLEARED_MARKER_PATH on disk at all.
    pre_existing_state = _fake_state()
    for i in range(100):
        trade = _make_completed_trade(pre_existing_state, suffix=f"preexisting{i}", entry_timestamp="2026-06-22T00:00:00+00:00")
        pre_existing_state.completed_setups[trade.setup_id] = trade
        pre_existing_state.setup_history[trade.setup_id] = [{"from_state": None, "to_state": "ENTRY_READY"}]
    setup_history_store.save_setup_history_store(pre_existing_state)
    assert not setup_history_store.HISTORY_CLEARED_MARKER_PATH.exists()
    assert setup_history_store.STORE_PATH.exists()

    boot_state = _fake_state()
    ran = setup_history_store.run_one_time_history_clear_migration(boot_state)
    setup_history_store.load_setup_history_store(boot_state)

    assert ran is True
    assert boot_state.completed_setups == {}, "the 100 pre-existing entries must be wiped"
    assert setup_history_store.HISTORY_CLEARED_MARKER_PATH.exists()
    # The data file itself now reflects the empty state, not just the marker.
    reloaded_after_migration = _fake_state()
    setup_history_store.load_setup_history_store(reloaded_after_migration)
    assert reloaded_after_migration.completed_setups == {}


def test_one_time_migration_wipes_existing_data_exactly_once(monkeypatch, tmp_path) -> None:
    """The migration must wipe whatever is already persisted the first time
    it runs (no marker file yet), then never run again once the marker
    exists - new data saved after the first run must survive every later
    restart instead of being wiped again."""
    _redirect_paths(monkeypatch, tmp_path)
    pre_existing_state = _fake_state()
    old_trade = _make_completed_trade(pre_existing_state, suffix="old1", entry_timestamp="2026-06-22T00:00:00+00:00")
    pre_existing_state.completed_setups[old_trade.setup_id] = old_trade
    pre_existing_state.setup_history[old_trade.setup_id] = [{"from_state": None, "to_state": "ENTRY_READY"}]
    setup_history_store.save_setup_history_store(pre_existing_state)

    first_boot_state = _fake_state()
    ran_first_time = setup_history_store.run_one_time_history_clear_migration(first_boot_state)
    setup_history_store.load_setup_history_store(first_boot_state)

    assert ran_first_time is True
    assert first_boot_state.completed_setups == {}, "existing June-22-style data must be wiped on first run"

    new_trade = _make_completed_trade(first_boot_state, suffix="new1", entry_timestamp="2026-06-24T00:00:00+00:00")
    first_boot_state.completed_setups[new_trade.setup_id] = new_trade
    first_boot_state.setup_history[new_trade.setup_id] = [{"from_state": None, "to_state": "ENTRY_READY"}]
    setup_history_store.save_setup_history_store(first_boot_state)

    second_boot_state = _fake_state()
    ran_second_time = setup_history_store.run_one_time_history_clear_migration(second_boot_state)
    setup_history_store.load_setup_history_store(second_boot_state)

    assert ran_second_time is False, "the migration must not run a second time once the marker file exists"
    assert new_trade.setup_id in second_boot_state.completed_setups, "data saved after the one-time migration must survive a later restart"
    assert old_trade.setup_id not in second_boot_state.completed_setups


def test_clear_setup_history_clears_in_memory_and_deletes_the_file(monkeypatch, tmp_path) -> None:
    """The on-demand admin clear (POST /api/admin/clear-setup-history) must
    clear completed_setups/invalidated_setups in memory AND delete the
    persisted file from disk in the same call, so a later load (e.g. after
    a subsequent restart) finds nothing left over."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    completed_trade = _make_completed_trade(state, suffix="manual_completed1", entry_timestamp="2026-06-24T00:00:00+00:00")
    state.completed_setups[completed_trade.setup_id] = completed_trade
    state.setup_history[completed_trade.setup_id] = [{"from_state": None, "to_state": "ENTRY_READY"}]
    setup_history_store.save_setup_history_store(state)
    assert setup_history_store.STORE_PATH.exists()

    completed_count, invalidated_count = setup_history_store.clear_setup_history(state)

    assert (completed_count, invalidated_count) == (1, 0)
    assert state.completed_setups == {}
    assert completed_trade.setup_id not in state.setup_history
    assert not setup_history_store.STORE_PATH.exists(), "the persisted file must be deleted, not just emptied"

    reloaded_state = _fake_state()
    setup_history_store.load_setup_history_store(reloaded_state)
    assert reloaded_state.completed_setups == {}


def test_clear_setup_history_does_not_touch_in_progress(monkeypatch, tmp_path) -> None:
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    active = _make_completed_trade(state, suffix="active_manual1", entry_timestamp="2026-06-24T00:00:00+00:00")
    state.setups[active.setup_id] = active
    state.setup_history[active.setup_id] = [{"from_state": None, "to_state": "ACTIVE"}]

    setup_history_store.clear_setup_history(state)

    assert active.setup_id in state.setups
    assert active.setup_id in state.setup_history


def test_load_with_no_persisted_file_returns_empty(monkeypatch, tmp_path) -> None:
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()

    counts = setup_history_store.load_setup_history_store(state)

    assert counts == (0, 0)
    assert state.completed_setups == {}
    assert state.invalidated_setups == {}


def test_load_with_corrupt_file_does_not_raise(monkeypatch, tmp_path) -> None:
    """A corrupt or unreadable persisted file must degrade to an empty
    starting point, never crash the app at startup."""
    _redirect_paths(monkeypatch, tmp_path)
    setup_history_store.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    setup_history_store.STORE_PATH.write_text("{not valid json", encoding="utf-8")
    state = _fake_state()

    counts = setup_history_store.load_setup_history_store(state)

    assert counts == (0, 0)
