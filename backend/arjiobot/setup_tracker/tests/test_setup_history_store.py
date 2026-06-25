"""Tests for disk-backed completed/invalidated Setup Radar persistence.

Every test here redirects STORE_PATH to a pytest tmp_path - never the real
backend/data/ files.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from arjiobot.live_setup_detection import _filter_resolved_swings, _setup_from_trade, move_setup_to_completed
from arjiobot.setup_tracker import setup_history_store
from arjiobot.setup_tracker.setup_models import SetupDirection, SetupState, SetupStatus, build_swing_dedup_key


def _fake_state() -> SimpleNamespace:
    return SimpleNamespace(
        setups={},
        invalidated_setups=[],
        completed_setups=[],
        resolved_setup_ids=set(),
        resolved_swing_keys=set(),
        setup_history={},
        history_cleared_at=None,
    )


def _redirect_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(setup_history_store, "STORE_PATH", tmp_path / "setup_history_store.json")


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


def test_save_writes_completed_and_invalidated_in_their_current_list_order(monkeypatch, tmp_path) -> None:
    """save_setup_history_store mirrors the in-memory lists exactly, in their
    current order (newest-first, append-only - see
    live_setup_detection.py's _append_resolved_setup) - it never re-sorts or
    filters anything itself; the in-memory list is already correct by
    construction."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    trade = _make_completed_trade(state, suffix="rt1", entry_timestamp="2026-06-24T01:30:00+00:00")
    state.completed_setups.append(trade)
    state.setup_history[trade.setup_id] = [{"from_state": None, "to_state": "ENTRY_READY", "changed_at": "2026-06-24T01:30:00+00:00", "reason": "test", "source": "TEST"}]

    setup_history_store.save_setup_history_store(state)
    payload = json.loads(setup_history_store.STORE_PATH.read_text(encoding="utf-8"))

    assert payload["invalidated"] == []
    assert len(payload["completed"]) == 1
    [saved] = payload["completed"]
    assert saved["setup_id"] == trade.setup_id
    assert saved["current_state"] == SetupState.ENTRY_READY.value
    assert saved["status"] == SetupStatus.ENTRY_READY.value
    assert payload["setup_history"][trade.setup_id] == state.setup_history[trade.setup_id]
    assert payload["cleared_at"] is None


def test_save_never_writes_in_progress_setups(monkeypatch, tmp_path) -> None:
    """state.setups (IN PROGRESS) must never be written to disk - only
    completed_setups/invalidated_setups are persisted."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    active = _make_completed_trade(state, suffix="active1", entry_timestamp="2026-06-24T01:30:00+00:00")
    state.setups[active.setup_id] = active  # deliberately placed in IN PROGRESS, not completed_setups

    setup_history_store.save_setup_history_store(state)
    payload = json.loads(setup_history_store.STORE_PATH.read_text(encoding="utf-8"))

    assert payload["completed"] == []
    assert payload["invalidated"] == []
    assert active.setup_id not in json.dumps(payload)


def test_save_includes_history_cleared_at_when_set(monkeypatch, tmp_path) -> None:
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    setup_history_store.wipe_setup_history(state)

    cleared_at = state.history_cleared_at
    trade = _make_completed_trade(state, suffix="after1", entry_timestamp=cleared_at.isoformat())
    state.completed_setups.append(trade)
    setup_history_store.save_setup_history_store(state)

    payload = json.loads(setup_history_store.STORE_PATH.read_text(encoding="utf-8"))
    assert payload["cleared_at"] == cleared_at.isoformat()


def test_wipe_setup_history_clears_memory_and_overwrites_file_with_empty_shape(monkeypatch, tmp_path) -> None:
    """Fix 5 (fresh start): wipe_setup_history must clear completed_setups/
    invalidated_setups in memory, clear the seen-setups dedup cache, record
    history_cleared_at, and overwrite the persisted file with the exact
    empty shape {"completed": [], "invalidated": [], "cleared_at": ...} -
    regardless of what the file contained before this call. Used both by the
    admin clear endpoint and once, unconditionally, on every process boot."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    completed_trade = _make_completed_trade(state, suffix="manual_completed1", entry_timestamp="2026-06-24T00:00:00+00:00")
    state.completed_setups.append(completed_trade)
    state.resolved_setup_ids.add(completed_trade.setup_id)
    state.setup_history[completed_trade.setup_id] = [{"from_state": None, "to_state": "ENTRY_READY"}]
    setup_history_store.save_setup_history_store(state)
    assert setup_history_store.STORE_PATH.exists()

    completed_count, invalidated_count = setup_history_store.wipe_setup_history(state)

    assert (completed_count, invalidated_count) == (1, 0)
    assert state.completed_setups == []
    assert state.invalidated_setups == []
    assert state.resolved_setup_ids == set()
    assert completed_trade.setup_id not in state.setup_history
    assert state.history_cleared_at is not None

    payload = json.loads(setup_history_store.STORE_PATH.read_text(encoding="utf-8"))
    assert payload == {"completed": [], "invalidated": [], "cleared_at": state.history_cleared_at.isoformat(), "setup_history": {}}


def test_wipe_setup_history_overwrites_a_file_with_old_unrelated_content(monkeypatch, tmp_path) -> None:
    """Fix 5, the exact scenario: setup_history_store.json already contains
    entries from a previous deployment session - the wipe must overwrite it
    with the empty shape regardless, not merely check whether the file
    exists."""
    _redirect_paths(monkeypatch, tmp_path)
    setup_history_store.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    setup_history_store.STORE_PATH.write_text(json.dumps({"completed": [{"setup_id": "set_old_session"}], "invalidated": [], "cleared_at": None, "setup_history": {}}), encoding="utf-8")
    state = _fake_state()

    setup_history_store.wipe_setup_history(state)

    payload = json.loads(setup_history_store.STORE_PATH.read_text(encoding="utf-8"))
    assert payload["completed"] == []
    assert "set_old_session" not in json.dumps(payload)


def test_wipe_setup_history_does_not_touch_in_progress(monkeypatch, tmp_path) -> None:
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    active = _make_completed_trade(state, suffix="active_manual1", entry_timestamp="2026-06-24T00:00:00+00:00")
    state.setups[active.setup_id] = active
    state.setup_history[active.setup_id] = [{"from_state": None, "to_state": "ACTIVE"}]

    setup_history_store.wipe_setup_history(state)

    assert active.setup_id in state.setups
    assert active.setup_id in state.setup_history


def test_resolved_setup_ids_blocks_a_setup_id_from_being_written_twice(monkeypatch, tmp_path) -> None:
    """The seen-setups dedup cache (Fix 4): once a setup_id resolves into
    completed_setups, _append_resolved_setup must silently refuse to write
    it again (e.g. the live detection funnel re-deriving the exact same
    deterministic setup_id from its rolling candle buffer on a later poll) -
    this is what keeps the append-only list stable between polls."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    trade = _make_completed_trade(state, suffix="resurrect1", entry_timestamp="2026-06-24T00:00:00+00:00")
    move_setup_to_completed(state, trade)
    assert state.completed_setups == [trade]

    move_setup_to_completed(state, trade)
    assert state.completed_setups == [trade], "writing the same setup_id a second time must be a no-op"


def test_wipe_setup_history_clears_the_dedup_cache_so_a_fresh_session_can_rewrite_the_same_id(monkeypatch, tmp_path) -> None:
    """Fix 5: wipe_setup_history clears resolved_setup_ids too, specifically
    so old setup_ids from a previous deployment session never block fresh
    setups from this one - even one that happens to hash to the exact same
    deterministic setup_id (e.g. identical symbol/direction/timestamp)."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    trade = _make_completed_trade(state, suffix="resurrect1", entry_timestamp="2026-06-24T00:00:00+00:00")
    move_setup_to_completed(state, trade)
    assert state.completed_setups == [trade]

    setup_history_store.wipe_setup_history(state)
    assert state.completed_setups == []

    move_setup_to_completed(state, trade)
    assert state.completed_setups == [trade], "after a wipe, the same setup_id must be writable again, not permanently blocked"


def test_wipe_setup_history_clears_swing_cache_so_previous_session_swings_can_reenter_funnel(monkeypatch, tmp_path) -> None:
    """wipe_setup_history clears resolved_swing_keys entirely on every deploy
    so the funnel re-evaluates all current swings from scratch on the first
    poll - a swing resolved in a prior session is NOT permanently blocked from
    re-entering, because the staleness gate (_expire_if_stale, now using
    detected_at_wallclock) handles age correctly once detection runs."""
    _redirect_paths(monkeypatch, tmp_path)
    previous_session_state = _fake_state()
    trade = _make_completed_trade(previous_session_state, suffix="prev_session1", entry_timestamp="2026-06-20T00:00:00+00:00")
    move_setup_to_completed(previous_session_state, trade)
    assert setup_history_store.STORE_PATH.exists()

    # Simulates the process restarting: a brand new ApiState, but STORE_PATH
    # on disk still holds exactly what the previous session wrote.
    new_session_state = _fake_state()
    completed_count, invalidated_count = setup_history_store.wipe_setup_history(new_session_state)

    assert (completed_count, invalidated_count) == (0, 0), "the new session's own in-memory lists start empty, by construction"
    assert new_session_state.completed_setups == []
    assert new_session_state.invalidated_setups == []
    # resolved_swing_keys must be EMPTY after wipe - prior session keys are not
    # carried over, so the funnel re-evaluates all swings on the first poll.
    assert len(new_session_state.resolved_swing_keys) == 0

    payload = json.loads(setup_history_store.STORE_PATH.read_text(encoding="utf-8"))
    assert payload == {"completed": [], "invalidated": [], "cleared_at": new_session_state.history_cleared_at.isoformat(), "setup_history": {}}

    # And with an empty cache the swing passes _filter_resolved_swings and
    # reaches the detection funnel normally on the next poll.
    swing = SimpleNamespace(symbol=trade.symbol, swing_id="whatever", right_candle=SimpleNamespace(timestamp=trade.created_at))
    assert _filter_resolved_swings(new_session_state, [swing], direction=trade.direction.value) == [swing]


# ---------------------------------------------------------------------------
# load_setup_history_for_display (new startup path - Fix 5)
# ---------------------------------------------------------------------------

def test_load_setup_history_for_display_populates_lists_and_seeds_setup_ids(monkeypatch, tmp_path) -> None:
    """Fix 5: load_setup_history_for_display reads the JSON file and populates
    completed_setups/invalidated_setups for UI display. resolved_setup_ids is
    seeded (to prevent duplicate writes for the same setup_id on the first
    poll), but resolved_swing_keys starts EMPTY - the pre-funnel staleness
    filter handles old swings on the first poll."""
    _redirect_paths(monkeypatch, tmp_path)
    # Simulate a previous session that wrote history to disk.
    prev_state = _fake_state()
    trade = _make_completed_trade(prev_state, suffix="load1", entry_timestamp="2026-06-24T01:00:00+00:00")
    move_setup_to_completed(prev_state, trade)
    assert setup_history_store.STORE_PATH.exists()

    # New session loads history - starts with empty in-memory state.
    new_state = _fake_state()
    completed_count, invalidated_count = setup_history_store.load_setup_history_for_display(new_state)

    assert (completed_count, invalidated_count) == (1, 0)
    assert len(new_state.completed_setups) == 1
    assert new_state.completed_setups[0].setup_id == trade.setup_id
    assert new_state.completed_setups[0].symbol == trade.symbol
    assert new_state.completed_setups[0].direction == SetupDirection.BEARISH
    # resolved_setup_ids seeded so no duplicate is created for this setup.
    assert trade.setup_id in new_state.resolved_setup_ids
    # resolved_swing_keys MUST be empty - staleness filter handles old swings.
    assert len(new_state.resolved_swing_keys) == 0


def test_load_setup_history_for_display_leaves_swing_cache_empty(monkeypatch, tmp_path) -> None:
    """The swing-level dedup cache must start empty after load so fresh swings
    are never blocked by prior session keys."""
    _redirect_paths(monkeypatch, tmp_path)
    prev_state = _fake_state()
    for i in range(5):
        t = _make_completed_trade(prev_state, suffix=f"s{i}", entry_timestamp=f"2026-06-2{i}T00:00:00+00:00")
        move_setup_to_completed(prev_state, t)

    new_state = _fake_state()
    setup_history_store.load_setup_history_for_display(new_state)

    assert len(new_state.completed_setups) == 5
    assert len(new_state.resolved_swing_keys) == 0


def test_load_setup_history_for_display_with_no_file_starts_empty(monkeypatch, tmp_path) -> None:
    """If no JSON file exists yet (fresh deploy) load returns (0, 0) and
    leaves all state empty."""
    _redirect_paths(monkeypatch, tmp_path)
    state = _fake_state()
    completed_count, invalidated_count = setup_history_store.load_setup_history_for_display(state)

    assert (completed_count, invalidated_count) == (0, 0)
    assert state.completed_setups == []
    assert state.invalidated_setups == []
    assert len(state.resolved_setup_ids) == 0
    assert len(state.resolved_swing_keys) == 0


def test_load_setup_history_for_display_with_corrupt_file_starts_empty(monkeypatch, tmp_path) -> None:
    """A corrupt or unreadable JSON file must be silently tolerated - the bot
    starts with empty visible lists rather than crashing at boot."""
    _redirect_paths(monkeypatch, tmp_path)
    setup_history_store.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    setup_history_store.STORE_PATH.write_text("not valid json {{{", encoding="utf-8")
    state = _fake_state()

    completed_count, invalidated_count = setup_history_store.load_setup_history_for_display(state)

    assert (completed_count, invalidated_count) == (0, 0)
    assert state.completed_setups == []
