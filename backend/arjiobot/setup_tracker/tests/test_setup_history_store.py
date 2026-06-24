"""Tests for disk-backed completed/invalidated Setup Radar persistence.

Every test here redirects STORE_PATH to a pytest tmp_path - never the real
backend/data/ files.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from arjiobot.live_setup_detection import _setup_from_trade, move_setup_to_completed
from arjiobot.setup_tracker import setup_history_store
from arjiobot.setup_tracker.setup_models import SetupState, SetupStatus


def _fake_state() -> SimpleNamespace:
    return SimpleNamespace(setups={}, invalidated_setups=[], completed_setups=[], resolved_setup_ids=set(), setup_history={}, history_cleared_at=None)


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
