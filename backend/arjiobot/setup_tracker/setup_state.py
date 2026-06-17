"""State transition helpers for Setup Tracker."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from arjiobot.market_data.candle_models import ensure_utc
from arjiobot.setup_tracker.setup_models import Setup, SetupState, SetupStatus, StateHistoryEntry


TERMINAL_STATES = {
    SetupState.ENTRY_READY,
    SetupState.INVALIDATED,
    SetupState.EXPIRED,
    SetupState.COMPLETED,
}


def status_for_state(state: SetupState) -> SetupStatus:
    """Return high-level status for a state."""
    if state is SetupState.ENTRY_READY:
        return SetupStatus.ENTRY_READY
    if state is SetupState.INVALIDATED:
        return SetupStatus.INVALIDATED
    if state is SetupState.EXPIRED:
        return SetupStatus.EXPIRED
    if state is SetupState.COMPLETED:
        return SetupStatus.COMPLETED
    return SetupStatus.ACTIVE


def transition_setup(
    setup: Setup,
    to_state: SetupState,
    *,
    changed_at: datetime,
    reason: str | None = None,
    triggering_object_type: str | None = None,
    triggering_object_id: str | None = None,
    progress_percent: float | None = None,
) -> Setup:
    """Return setup with a recorded state transition."""
    changed_at_utc = ensure_utc(changed_at)
    entry = StateHistoryEntry(
        from_state=setup.current_state,
        to_state=to_state,
        changed_at=changed_at_utc,
        reason=reason,
        triggering_object_type=triggering_object_type,
        triggering_object_id=triggering_object_id,
    )
    return replace(
        setup,
        current_state=to_state,
        status=status_for_state(to_state),
        updated_at=changed_at_utc,
        progress_percent=setup.progress_percent if progress_percent is None else progress_percent,
        state_history=(*setup.state_history, entry),
    )
