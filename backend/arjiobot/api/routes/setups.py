"""Setup routes."""

from __future__ import annotations

from itertools import chain

from fastapi import APIRouter

from arjiobot.api.dependencies import ApiState, get_state
from arjiobot.api.errors import api_error
from arjiobot.api.routes.radar import radar_record
from arjiobot.api.schemas.common import ok
from arjiobot.setup_tracker.setup_history_store import filter_and_cap_history
from arjiobot.setup_tracker.setup_models import SetupState, SetupStatus

router = APIRouter(prefix="/api/setups", tags=["setups"])

# Setup Radar page spec names these exact paths. Same handlers/data as the
# /api/setups/* routes above (kept as-is since the frontend already calls
# them) - this is a second router exposing identical responses at the paths
# the spec asks for, not a duplicate implementation.
setup_radar_router = APIRouter(prefix="/api/setup-radar", tags=["setup-radar"])


def _all_setups(state: ApiState):
    """Every tracked setup across all three stores - in-progress (uncapped),
    invalidated (age-filtered + capped at 100), completed (age-filtered +
    capped at 100). See live_setup_detection.py's _store_setup/
    move_setup_to_completed for how a setup ends up in exactly one of these
    at any given time. filter_and_cap_history is read-only (returns a new
    dict, never mutates state.invalidated_setups/completed_setups
    themselves) - applied here defensively, since wall-clock time alone can
    push a setup past the 1-hour age limit between writes."""
    return chain(state.setups.values(), filter_and_cap_history(state.invalidated_setups).values(), filter_and_cap_history(state.completed_setups).values())


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

    filter_and_cap_history (age + 100-cap) is applied here too, not just at
    load/write time - wall-clock time passing alone can push a setup past
    the 1-hour age limit between writes, with nothing to re-trigger
    filtering until the next one."""
    setups = sorted(filter_and_cap_history(get_state().completed_setups).values(), key=lambda setup: setup.completed_at or setup.updated_at, reverse=True)
    return ok(tuple(radar_record(setup) for setup in setups))


@router.get("/invalidated")
def invalidated():
    setups = sorted(filter_and_cap_history(get_state().invalidated_setups).values(), key=lambda setup: setup.invalidated_at or setup.updated_at, reverse=True)
    return ok(tuple(radar_record(setup) for setup in setups))


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
    setup = state.setups.get(setup_id) or state.invalidated_setups.get(setup_id) or state.completed_setups.get(setup_id)
    if setup is None:
        raise api_error(404, "SETUP_NOT_FOUND", "setup not found")
    return ok(radar_record(setup))


@router.get("/{setup_id}/history")
def history(setup_id: str):
    return ok(get_state().setup_history.get(setup_id, []))
