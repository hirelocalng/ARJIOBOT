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


def _all_setups(state: ApiState):
    """Every tracked setup across all three stores - in-progress (uncapped),
    invalidated (capped at 100), completed (capped at 100). See
    live_setup_detection.py's _store_setup/move_setup_to_completed for how a
    setup ends up in exactly one of these at any given time."""
    return chain(state.setups.values(), state.invalidated_setups.values(), state.completed_setups.values())


@router.get("")
def list_setups():
    return ok(tuple(radar_record(setup) for setup in _all_setups(get_state())))


@router.get("/entry-ready")
def entry_ready():
    return ok(tuple(radar_record(setup) for setup in get_state().setups.values() if setup.current_state is SetupState.ENTRY_READY))


@router.get("/in-progress")
def in_progress():
    """Active attempts, every one of them - not deduplicated per symbol, since
    a pair can legitimately have more than one concurrent attempt (e.g. a
    bearish and a bullish swing forming at once). Not capped - state.setups
    only ever holds in-progress/pending-execution setups now."""
    setups = sorted(
        (setup for setup in get_state().setups.values() if setup.status is SetupStatus.ACTIVE),
        key=lambda setup: setup.progress_percent,
        reverse=True,
    )
    return ok(tuple(radar_record(setup) for setup in setups))


@router.get("/completed")
def completed():
    """COMPLETED (attempt-tracker's own "reached 100%" marker) and
    ENTRY_READY (the real tradable setup, still pending submission - see
    _setup_from_trade) both represent "finished successfully", so both
    belong here. Once an ENTRY_READY setup is actually submitted,
    move_setup_to_completed moves it into completed_setups too, so this
    union never double-counts or drops it."""
    state = get_state()
    pending_entry_ready = (setup for setup in state.setups.values() if setup.status is SetupStatus.ENTRY_READY)
    setups = sorted(chain(pending_entry_ready, state.completed_setups.values()), key=lambda setup: setup.updated_at, reverse=True)
    return ok(tuple(radar_record(setup) for setup in setups))


@router.get("/invalidated")
def invalidated():
    setups = sorted(get_state().invalidated_setups.values(), key=lambda setup: setup.invalidated_at or setup.updated_at, reverse=True)
    return ok(tuple(radar_record(setup) for setup in setups))


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
