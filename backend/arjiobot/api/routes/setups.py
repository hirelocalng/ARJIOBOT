"""Setup routes."""

from __future__ import annotations

from itertools import chain

from fastapi import APIRouter

from arjiobot.api.dependencies import ApiState, get_state
from arjiobot.api.errors import api_error
from arjiobot.api.routes.radar import radar_record
from arjiobot.api.schemas.common import ok
from arjiobot.setup_tracker.setup_models import SetupState, SetupStatus

router = APIRouter(prefix="/api/setups", tags=["setups"])

# Setup Radar page spec names these exact paths. Same handlers/data as the
# /api/setups/* routes above (kept as-is since the frontend already calls
# them) - this is a second router exposing identical responses at the paths
# the spec asks for, not a duplicate implementation.
setup_radar_router = APIRouter(prefix="/api/setup-radar", tags=["setup-radar"])


def _all_setups(state: ApiState):
    """Every tracked setup across all three stores - in-progress (uncapped),
    invalidated (append-only, capped at 100), completed (append-only, capped
    at 100, newest-first - see live_setup_detection.py's
    _append_resolved_setup for how a setup ends up in exactly one of these,
    exactly once, for good)."""
    return chain(state.setups.values(), state.invalidated_setups, state.completed_setups)


@router.get("")
def list_setups():
    return ok(tuple(radar_record(setup) for setup in _all_setups(get_state())))


@router.get("/entry-ready")
def entry_ready():
    return ok(tuple(radar_record(setup) for setup in get_state().setups.values() if setup.current_state is SetupState.ENTRY_READY))


@router.get("/in-progress")
def in_progress():
    """Active attempts AND real ENTRY_READY setups still awaiting execution's
    verdict ("pending execution", see should_leave_in_progress) - not
    deduplicated per symbol, since a pair can legitimately have more than one
    concurrent attempt (e.g. a bearish and a bullish swing forming at once).
    Not capped - state.setups only ever holds in-progress/pending-execution
    setups now. A pending ENTRY_READY setup must stay visible here, not jump
    to COMPLETED, until live_automation confirms a trade opened or explicitly
    rejects it (or the staleness gate expires it) - see live_automation.py's
    _process_setup/_resolve_rejected_setup."""
    setups = sorted(
        (setup for setup in get_state().setups.values() if setup.status in (SetupStatus.ACTIVE, SetupStatus.ENTRY_READY)),
        key=lambda setup: setup.progress_percent,
        reverse=True,
    )
    return ok(tuple(radar_record(setup) for setup in setups))


@router.get("/completed")
def completed():
    """Only setups execution has actually resolved - a real ENTRY_READY setup
    still pending submission belongs in IN PROGRESS (see in_progress() above),
    not here, until move_setup_to_completed actually moves it (a confirmed
    trade or an explicit rejection - see live_automation.py's _process_setup).
    The attempt-tracker's own "reached 100%" diagnostic marker lands directly
    in completed_setups already (see _store_setup), so it needs no separate
    union with state.setups here.

    Returned exactly in list order (newest-first, append-only - see
    _append_resolved_setup) - never re-sorted here, so this is byte-for-byte
    stable between polls unless a new entry was just added."""
    return ok(tuple(radar_record(setup) for setup in get_state().completed_setups))


@router.get("/invalidated")
def invalidated():
    return ok(tuple(radar_record(setup) for setup in get_state().invalidated_setups))


@setup_radar_router.get("/in-progress")
def setup_radar_in_progress():
    return in_progress()


@setup_radar_router.get("/invalidated")
def setup_radar_invalidated():
    return invalidated()


@setup_radar_router.get("/completed")
def setup_radar_completed():
    return completed()


@router.get("/progress/{percent}")
def progress(percent: str):
    threshold = float(percent)
    return ok(tuple(radar_record(setup) for setup in _all_setups(get_state()) if setup.progress_percent >= threshold))


@router.get("/{setup_id}")
def get_setup(setup_id: str):
    state = get_state()
    setup = state.setups.get(setup_id) or next((s for s in (*state.invalidated_setups, *state.completed_setups) if s.setup_id == setup_id), None)
    if setup is None:
        raise api_error(404, "SETUP_NOT_FOUND", "setup not found")
    return ok(radar_record(setup))


@router.get("/{setup_id}/history")
def history(setup_id: str):
    return ok(get_state().setup_history.get(setup_id, []))
