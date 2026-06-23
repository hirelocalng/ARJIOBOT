"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import pytest

from arjiobot.setup_tracker import setup_history_store


@pytest.fixture(autouse=True)
def _isolate_setup_history_store(tmp_path, monkeypatch):
    """Redirect completed/invalidated setup persistence to a per-test
    tmp_path for every test in the suite, automatically.

    Without this, any test that drives a setup to COMPLETED/INVALIDATED
    (most of arjiobot/tests/test_setup_radar_attempts.py, for example) would
    write to the real backend/data/setup_history_store.json as a side
    effect - and worse, could create the real
    backend/data/.history_cleared marker file outside of an actual deploy,
    which would silently make the real one-time wipe never run in
    production.
    """
    monkeypatch.setattr(setup_history_store, "STORE_PATH", tmp_path / "setup_history_store.json")
    monkeypatch.setattr(setup_history_store, "HISTORY_CLEARED_MARKER_PATH", tmp_path / ".history_cleared")
