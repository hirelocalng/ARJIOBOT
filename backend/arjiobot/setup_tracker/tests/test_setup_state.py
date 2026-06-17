"""State transition tests."""

from __future__ import annotations

from datetime import datetime, timezone

from arjiobot.setup_tracker.setup_models import SetupState
from arjiobot.setup_tracker.setup_state import status_for_state, transition_setup
from arjiobot.setup_tracker.tests.test_setup_models import make_setup


def test_transition_records_history() -> None:
    setup = make_setup(progress_percent=15.0)
    changed_at = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)

    updated = transition_setup(setup, SetupState.SWING_16M_CONFIRMED, changed_at=changed_at, reason="swing")

    assert updated.current_state is SetupState.SWING_16M_CONFIRMED
    assert updated.state_history[-1].from_state is SetupState.WATCHING_HTF_FVG
    assert updated.state_history[-1].reason == "swing"


def test_status_for_terminal_states() -> None:
    assert status_for_state(SetupState.ENTRY_READY).value == "ENTRY_READY"
    assert status_for_state(SetupState.INVALIDATED).value == "INVALIDATED"

